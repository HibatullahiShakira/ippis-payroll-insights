"""
Upload review — checks uploaded files before anything is imported.

Every upload is read twice: first here, without touching the data, to produce a
report the user reviews; then for real, only after the user confirms. Format
drift (a renamed column, a new payslip layout, the wrong month) shows up as a
clear message on the review screen instead of as silently missing data.

Check levels:
    error   - the upload cannot be imported (the Confirm button is disabled)
    warning - something looks wrong; the user decides
    info    - worth knowing (e.g. how many payslips will be replaced)
    ok      - a check that passed
"""

from sqlalchemy import func

from ..extensions import db
from ..models.employee import Employee
from ..models.payslip import Payslip
from ..models.upload_report import UploadReport
from .excel_parser import FIELD_LABELS, OPTIONAL_FIELDS, REQUIRED_FIELDS, read_nominal_roll
from .pdf_parser import analyze_pdf

# A month-on-month headcount change bigger than this is flagged
HEADCOUNT_CHANGE_WARN = 0.10
# Itemised breakdowns not matching the printed totals above this share are flagged
ITEMISED_MISMATCH_WARN = 0.10

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]

_table_ready = False


def _ensure_table():
    """Create upload_reports on first use (the project has no migrations)."""
    global _table_ready
    if not _table_ready:
        UploadReport.__table__.create(db.engine, checkfirst=True)
        _table_ready = True


def save_report(batch_id, report):
    _ensure_table()
    row = UploadReport.query.filter_by(batch_id=batch_id).first() or UploadReport(batch_id=batch_id)
    row.report = report
    db.session.add(row)
    db.session.commit()


def load_report(batch_id):
    _ensure_table()
    row = UploadReport.query.filter_by(batch_id=batch_id).first()
    return row.report if row else None


def month_label(month_year):
    try:
        year, month = month_year.split("-")
        return f"{MONTH_NAMES[int(month) - 1]} {year}"
    except (ValueError, IndexError, AttributeError):
        return month_year or ""


def _pct(part, whole):
    return f"{part * 100 / whole:.0f}%" if whole else "0%"


def _ippis_for_month(month_year):
    rows = (
        db.session.query(Employee.ippis_number)
        .join(Payslip, Payslip.employee_id == Employee.id)
        .filter(Payslip.month_year == month_year)
        .all()
    )
    return {r[0] for r in rows}


def _review_pdf(pdf_path, month_year, checks):
    found = analyze_pdf(pdf_path)
    ippis_found = found.pop("ippis")
    payslips = found["payslips"]
    summary = {k: v for k, v in found.items() if k != "examples"}
    summary["examples"] = found["examples"]

    if payslips == 0:
        checks.append(("error", f"No payslips could be read from the {found['pages']}-page PDF. "
                                "It may be a scanned image or a different document."))
        return summary, set()

    checks.append(("ok", f"{payslips:,} payslips read for {month_label(month_year)} "
                         f"from {found['pages']:,} pages."))

    months = found["months"]
    if len(months) > 1:
        listed = ", ".join(f"{month_label(m)} ({n})" for m, n in sorted(months.items()))
        checks.append(("error", f"The PDF mixes payslips from more than one month: {listed}. "
                                "Upload one month per PDF."))

    if found["overflow_pages"]:
        checks.append(("info", f"{found['overflow_pages']} continuation page(s) for long payslips were skipped "
                               "(they carry no payslip of their own)."))
    if found["blank_pages"]:
        checks.append(("warning", f"{found['blank_pages']} page(s) have no readable text and were skipped. "
                                  "Scanned pages cannot be read."))
    if found["unrecognised_pages"]:
        checks.append(("warning", f"{found['unrecognised_pages']} page(s) look like payslips but could not be "
                                  "read. The payslip layout may have changed; see the examples below."))
    if found["duplicates"]:
        checks.append(("warning", f"{found['duplicates']} IPPIS number(s) appear on more than one payslip; "
                                  "only the last one will be kept."))

    if found["net_mismatch"]:
        checks.append(("warning", f"{found['net_mismatch']} payslip(s) where Gross minus Deductions does not "
                                  "equal Net Pay. The figures may have been read wrongly."))
    else:
        checks.append(("ok", "Gross minus Deductions equals Net Pay on every payslip."))

    missing = found["missing"]
    for key, label in (("name", "employee name"), ("grade", "grade"), ("gross", "gross earnings"), ("net", "net pay")):
        if missing[key]:
            checks.append(("warning", f"{missing[key]} payslip(s) have no {label}."))

    mismatched = found["itemised_mismatch"]
    if mismatched:
        level = "warning" if mismatched / payslips > ITEMISED_MISMATCH_WARN else "info"
        checks.append((level, f"{mismatched} payslip(s) ({_pct(mismatched, payslips)}) have an itemised "
                              "earnings/deductions list that does not add up to the printed totals, usually "
                              "because the list continues on an overflow page. Their totals are still saved "
                              "correctly."))

    # Compare with what is already on record
    existing = Payslip.query.filter_by(month_year=month_year).count()
    if existing:
        checks.append(("info", f"{month_label(month_year)} already has {existing:,} payslips on record; "
                               "they will be replaced by this upload."))

    previous = (
        db.session.query(func.max(Payslip.month_year))
        .filter(Payslip.month_year < month_year)
        .scalar()
    )
    summary["previous_month"] = previous
    if previous:
        prev_ippis = _ippis_for_month(previous)
        joined, left = len(ippis_found - prev_ippis), len(prev_ippis - ippis_found)
        summary.update(previous_count=len(prev_ippis), joined=joined, left=left)
        change = (payslips - len(prev_ippis)) / len(prev_ippis) if prev_ippis else 0
        message = (f"{payslips:,} payslips vs {len(prev_ippis):,} in {month_label(previous)} "
                   f"({joined} new, {left} no longer on the payroll).")
        checks.append(("warning" if abs(change) > HEADCOUNT_CHANGE_WARN else "ok",
                       ("Headcount changed by more than 10%: " if abs(change) > HEADCOUNT_CHANGE_WARN else "")
                       + message))

    known = {r[0] for r in db.session.query(Employee.ippis_number).filter(Employee.ippis_number.in_(ippis_found))}
    unknown = len(ippis_found - known)
    summary["not_on_record"] = unknown
    if unknown:
        checks.append(("info", f"{unknown} employee(s) on these payslips are not on record yet and will be added "
                               "(without department until a nominal roll lists them)."))
    summary["ippis_count"] = len(ippis_found)
    return summary, ippis_found


def _review_excel(excel_path, checks):
    sheet = read_nominal_roll(excel_path)
    summary = {
        "header_row": sheet["header_row"],
        "columns": {FIELD_LABELS[f]: h for f, h in sheet["headers"].items()},
        "unrecognised_columns": sheet["unrecognised"],
        "rows": len(sheet["records"]),
        "skipped_rows": len(sheet["skipped_rows"]),
        "skipped_examples": [{"row": r, "reason": why} for r, why in sheet["skipped_rows"][:10]],
    }

    if sheet["header_row"] is None:
        checks.append(("error", "No header row with an IPPIS Number column was found in the first rows of the "
                                "Excel sheet. Check that the right sheet is first in the workbook."))
        return summary, set()

    found_fields = set(sheet["col_map"])
    missing_required = [FIELD_LABELS[f] for f in REQUIRED_FIELDS if f not in found_fields]
    if missing_required:
        checks.append(("error", f"The Excel sheet has no {' or '.join(missing_required)} column "
                                f"(header found on row {sheet['header_row']})."))
        return summary, set()

    records = sheet["records"]
    if not records:
        checks.append(("error", "The Excel sheet has a header row but no employee rows."))
        return summary, set()

    checks.append(("ok", f"{len(records):,} employees read from the nominal roll "
                         f"(header on row {sheet['header_row']})."))

    missing_optional = [FIELD_LABELS[f] for f in OPTIONAL_FIELDS if f not in found_fields and f != "serial_no"]
    if missing_optional:
        checks.append(("warning", f"No {', '.join(missing_optional)} column found. Those details will be kept "
                                  "as they are on record (GL is also refreshed from the payslips)."))
    if sheet["unrecognised"]:
        checks.append(("info", f"Columns ignored: {', '.join(sheet['unrecognised'][:10])}."))
    if sheet["skipped_rows"]:
        rows = ", ".join(str(r) for r, _ in sheet["skipped_rows"][:8])
        checks.append(("warning", f"{len(sheet['skipped_rows'])} row(s) skipped for having no IPPIS number or "
                                  f"name (rows {rows}{'…' if len(sheet['skipped_rows']) > 8 else ''})."))

    ippis = [r["ippis_number"] for r in records]
    duplicates = len(ippis) - len(set(ippis))
    if duplicates:
        checks.append(("warning", f"{duplicates} IPPIS number(s) are listed more than once; the last row wins."))

    sheet_ippis = set(ippis)
    known = {r[0] for r in db.session.query(Employee.ippis_number)}
    new, absent = len(sheet_ippis - known), len(known - sheet_ippis)
    summary.update(new_employees=new, not_in_sheet=absent)
    if new:
        checks.append(("info", f"{new} employee(s) are new and will be added."))
    if absent:
        checks.append(("info", f"{absent} employee(s) on record are not in this sheet; they are kept, not deleted."))
    return summary, sheet_ippis


def build_report(month_year, excel_path=None, pdf_path=None):
    """Read the files without importing anything and return the review report."""
    checks = []
    report = {"month_year": month_year, "month_label": month_label(month_year)}

    pdf_ippis = excel_ippis = None
    if pdf_path:
        report["pdf"], pdf_ippis = _review_pdf(pdf_path, month_year, checks)
    if excel_path:
        report["excel"], excel_ippis = _review_excel(excel_path, checks)

    if pdf_ippis and excel_ippis:
        missing = len(pdf_ippis - excel_ippis)
        if missing:
            checks.append(("info", f"{missing} employee(s) have a payslip but are not on the nominal roll."))

    order = {"error": 0, "warning": 1, "info": 2, "ok": 3}
    report["checks"] = [{"level": level, "message": message}
                        for level, message in sorted(checks, key=lambda c: order[c[0]])]
    report["errors"] = sum(1 for c in checks if c[0] == "error")
    report["warnings"] = sum(1 for c in checks if c[0] == "warning")
    report["can_import"] = report["errors"] == 0
    return report
