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

import os

from sqlalchemy import func

from ..extensions import db
from ..models.employee import Employee
from ..models.payslip import Payslip
from ..models.upload_report import UploadReport
from .excel_parser import (
    FIELD_LABELS, OPTIONAL_FIELDS, REQUIRED_FIELDS, SHORT_IPPIS_LIMIT, read_nominal_roll, remap_file_number_rows,
)
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


def _review_pdf(pdf_path, month_year, checks, reprocess=False):
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
        checks.append(("info", f"{found['overflow_pages']} blank page(s) carrying only the IPPIS letterhead "
                               "were skipped."))
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
        checks.append((level, f"{mismatched} payslip(s) ({_pct(mismatched, payslips)}) have more "
                              "earnings/deductions than IPPIS printed: the list is cut off at the bottom of the "
                              "page and the rest is not in the PDF. The difference is saved as one line, "
                              "'Not itemised on payslip', so every breakdown still adds up to its printed total."))

    # Compare with what is already on record
    existing = Payslip.query.filter_by(month_year=month_year).count()
    summary["existing_payslips"] = existing
    if existing and reprocess:
        checks.append(("info", f"Re-processing: the {existing:,} {month_label(month_year)} payslips on record "
                               "will be replaced by this re-read of the same stored PDF."))
    elif existing:
        # Each month is uploaded once; a second upload is how wrong data gets in
        checks.append(("error", f"{month_label(month_year)} payslips are already in the system ({existing:,} "
                                "payslips), so they cannot be uploaded again. "
                                "To refresh these payslips with the latest reading rules, use Re-process in Upload History. To replace them with a different file, an admin must first delete this month in Upload History."))

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

    # File Numbers typed in the IPPIS column: matched to the right employee where possible
    on_record = [
        {"ippis_number": i, "file_no": f, "name": n}
        for i, f, n in db.session.query(Employee.ippis_number, Employee.file_no, Employee.name)
    ]
    records, remapped = remap_file_number_rows(records, on_record)
    summary["file_numbers_in_ippis_column"] = len(remapped)
    if remapped:
        examples = ", ".join(f"{name.strip()} ({value} -> IPPIS {real})" for value, real, name in remapped[:3])
        checks.append(("warning", f"{len(remapped)} row(s) have the File No in the IPPIS column. Each matches an "
                                  f"employee's File No and name, so that employee will be updated instead of a "
                                  f"duplicate being created (e.g. {examples}). Please correct the sheet at source."))
    on_record_ippis = {e["ippis_number"] for e in on_record}
    unmatched_short = [r for r in records
                       if r["ippis_number"] < SHORT_IPPIS_LIMIT and r["ippis_number"] not in on_record_ippis]
    if unmatched_short:
        names = ", ".join(f"{r['name'].strip()} ({r['ippis_number']})" for r in unmatched_short[:5])
        checks.append(("warning", f"{len(unmatched_short)} new row(s) have a 5-digit-or-shorter IPPIS number, which "
                                  f"usually means a File No was typed in the IPPIS column: {names}"
                                  f"{'…' if len(unmatched_short) > 5 else ''}. They will be added as new employees; "
                                  "a later payslip with their real IPPIS number would then create a second record."))
    summary["short_ippis_rows"] = len(unmatched_short)

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

    _review_placement_changes(records, sheet["col_map"], summary, checks)
    return summary, sheet_ippis


PLACEMENT_FIELDS = ("department", "division", "gl")
# This many "moves back" (and at least half of all moves) look like an older roll re-uploaded
REVERSAL_WARN_COUNT = 10


def _same(a, b):
    a = str(a).strip().upper() if a is not None and str(a).strip() else None
    b = str(b).strip().upper() if b is not None and str(b).strip() else None
    return a == b


def _review_placement_changes(records, col_map, summary, checks):
    """
    How many employees this roll would move, and how many of those moves would
    simply undo the change the previous roll recorded for them: the signature of
    an older roll being uploaded again.
    """
    from ..models.employee_history import EmployeeHistory

    current = {
        row.ippis_number: row for row in db.session.query(
            Employee.id, Employee.ippis_number, Employee.department, Employee.division, Employee.gl)
    }
    latest_change = {}
    for h in (db.session.query(EmployeeHistory)
              .order_by(EmployeeHistory.employee_id, EmployeeHistory.change_date.desc(), EmployeeHistory.id.desc())):
        latest_change.setdefault(h.employee_id, h)

    fields = [f for f in PLACEMENT_FIELDS if f in col_map]
    moves, reversals, examples = 0, 0, {}
    for rec in {r["ippis_number"]: r for r in records}.values():
        emp = current.get(rec["ippis_number"])
        if emp is None:
            continue
        changed = [f for f in fields if not _same(rec[f], getattr(emp, f))]
        if not changed:
            continue
        moves += 1
        key = f"{emp.department or '-'} -> {rec['department'] if 'department' in col_map else emp.department}"
        examples[key] = examples.get(key, 0) + 1
        last = latest_change.get(emp.id)
        if last and all(_same(rec[f], getattr(last, f"old_{f}")) and _same(getattr(emp, f), getattr(last, f"new_{f}"))
                        for f in changed):
            reversals += 1
    summary.update(placement_changes=moves, placement_reversals=reversals)

    if not moves:
        checks.append(("ok", "No employee would change department, division or GL."))
        return
    top = ", ".join(f"{k} ({v})" for k, v in sorted(examples.items(), key=lambda kv: -kv[1])[:3])
    checks.append(("info", f"{moves} employee(s) would change department, division or GL, e.g. {top}."))
    if reversals >= REVERSAL_WARN_COUNT and reversals * 2 >= moves:
        checks.append(("warning", f"{reversals} of these {moves} changes would move staff BACK to where they were "
                                  "before the last nominal roll was imported. This usually means an older roll is "
                                  "being uploaded again. Import only if these moves are really correct."))


def _review_roll_month(excel_path, pdf_month, summary, checks):
    """Block a roll for the wrong month: not matching its payslips, or older than the newest roll imported."""
    from ..models.upload_batch import UploadBatch
    from .excel_parser import month_from_filename

    roll_month = month_from_filename(os.path.basename(excel_path))
    summary["roll_month"] = roll_month
    if roll_month is None:
        checks.append(("error", "The nominal roll's month could not be read from its file name, so it cannot be "
                                "checked against the rolls already imported. Rename the file to include the month "
                                "and year (e.g. 'NOMINAL ROLL OCT 2026.xlsx') and upload it again."))
        return

    if pdf_month and roll_month != pdf_month:
        checks.append(("error", f"The nominal roll is for {month_label(roll_month)} (from its file name) but the "
                                f"payslips are for {month_label(pdf_month)}. Upload the {month_label(pdf_month)} "
                                "nominal roll with these payslips. If the file name is wrong, correct it and upload again."))
        return

    latest, latest_at, imported_at = None, None, {}
    for name, uploaded_at in (db.session.query(UploadBatch.excel_filename, UploadBatch.uploaded_at)
                              .filter(UploadBatch.status == "completed", UploadBatch.excel_filename.isnot(None))):
        month = month_from_filename(name)
        if month:
            imported_at.setdefault(month, uploaded_at)
        if month and (latest is None or month > latest):
            latest, latest_at = month, uploaded_at
    summary["latest_roll_month"] = latest
    if roll_month in imported_at:
        when = f" on {imported_at[roll_month]:%d %b %Y}" if imported_at[roll_month] else ""
        checks.append(("error", f"The {month_label(roll_month)} nominal roll was already imported{when}, so it "
                                "cannot be uploaded again. Each month's roll is imported once. To replace it, an "
                                "admin must first delete the month in Upload History."))
    elif latest and roll_month < latest:
        when = f" on {latest_at:%d %b %Y}" if latest_at else ""
        checks.append(("error", f"This is the {month_label(roll_month)} nominal roll, but the {month_label(latest)} "
                                f"roll was already imported{when}. Importing an older roll would move staff back to "
                                "their old departments. If this file is actually a newer roll, correct the month "
                                "in its file name and upload again."))


def build_report(month_year, excel_path=None, pdf_path=None, reprocess=False):
    """Read the files without importing anything and return the review report."""
    checks = []
    report = {"month_year": month_year, "month_label": month_label(month_year)}

    pdf_ippis = excel_ippis = None
    if pdf_path:
        report["pdf"], pdf_ippis = _review_pdf(pdf_path, month_year, checks, reprocess=reprocess)
    if excel_path:
        report["excel"], excel_ippis = _review_excel(excel_path, checks)
        _review_roll_month(excel_path, month_year if pdf_path else None, report["excel"], checks)

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
