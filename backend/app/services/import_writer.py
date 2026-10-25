"""
Batched database writes for the nominal-roll and payslip imports.

The database is reached over the internet, where every round trip costs about a
quarter of a second, so writing row by row made a month's import take 6 minutes
(nominal roll) to 40+ minutes (payslips). Rows are written here in chunks — a
handful of statements per chunk — and progress is saved after every chunk so the
Upload page can show it.

If a chunk fails, it is rolled back and retried row by row, so one bad row is
skipped (and reported) without losing the rest.
"""

from sqlalchemy import String, delete, insert, update

from ..extensions import db
from ..models.employee import Employee
from ..models.employee_history import EmployeeHistory
from ..models.payslip import Payslip
from ..models.payslip_deduction import PayslipDeduction
from ..models.payslip_earning import PayslipEarning
from ..models.upload_batch import UploadBatch
from ..utils import normalize_gl

CHUNK_SIZE = 100

PAYSLIP_FIELDS = (
    "grade", "step", "gender", "tax_state", "designation", "date_of_birth", "date_of_first_appt",
    "trade_union", "bank_name", "account_number", "pfa_name", "pension_pin",
    "total_gross_earnings", "total_gross_deductions", "total_net_earnings",
    "cumulative_tax", "cumulative_income", "cumulative_pension", "cumulative_nhf", "pdf_page_num",
)


def fit(model, values):
    """Trim text values to their column's length, so one over-long value cannot fail a chunk."""
    columns = model.__table__.columns
    out = {}
    for key, value in values.items():
        column = columns.get(key)
        if (column is not None and isinstance(value, str) and isinstance(column.type, String)
                and column.type.length and len(value) > column.type.length):
            value = value[: column.type.length]
        out[key] = value
    return out


class Progress:
    """Saves how many records are done on the upload batch, for the progress bar."""

    def __init__(self, batch_id, offset=0):
        self.batch_id = batch_id
        self.offset = offset

    def report(self, done):
        if self.batch_id:
            db.session.execute(
                update(UploadBatch).where(UploadBatch.id == self.batch_id)
                .values(records_processed=self.offset + done)
            )
            db.session.commit()


def _chunks(items, size=CHUNK_SIZE):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def write_in_chunks(items, write_chunk, progress=None):
    """
    Run write_chunk(list) -> on_success callback for each chunk, committing each one.
    Returns (rows written, rows failed, first error message).
    """
    written = failed = 0
    first_error = None
    for chunk in _chunks(items):
        try:
            on_success = write_chunk(chunk)
            db.session.commit()
            on_success()
            written += len(chunk)
        except Exception:
            db.session.rollback()
            # Find the bad row(s): retry one at a time
            for item in chunk:
                try:
                    on_success = write_chunk([item])
                    db.session.commit()
                    on_success()
                    written += 1
                except Exception as e:
                    db.session.rollback()
                    failed += 1
                    if first_error is None:
                        first_error = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
        if progress:
            progress.report(written + failed)
    return written, failed, first_error


# ── Nominal roll ─────────────────────────────────────────────────────────────

def save_employees(records, col_map, batch_id=None, progress=None):
    """
    Create or update employees from nominal-roll records (see excel_parser.read_nominal_roll).
    A column missing from the sheet leaves that field as it is on record.
    """
    # One query for everyone on record, as plain values (not ORM objects)
    known = {
        row.ippis_number: dict(row._mapping)
        for row in db.session.execute(db.select(
            Employee.id, Employee.ippis_number, Employee.name, Employee.file_no,
            Employee.gl, Employee.department, Employee.division, Employee.serial_no,
        ))
    }
    # Rows carrying a File Number in the IPPIS column update the right employee
    from .excel_parser import remap_file_number_rows
    records, _ = remap_file_number_rows(records, known.values())
    # The last row wins when an IPPIS number is listed twice
    by_ippis = {r["ippis_number"]: r for r in records}

    def write_chunk(chunk):
        new_rows, updates, history = [], [], []
        for rec in chunk:
            current = known.get(rec["ippis_number"])
            target = {
                "name": rec["name"],
                "gl": rec["gl"] if "gl" in col_map else (current or {}).get("gl"),
                "department": rec["department"] if "department" in col_map else (current or {}).get("department"),
                "division": rec["division"] if "division" in col_map else (current or {}).get("division"),
            }
            if current is None:
                new_rows.append(fit(Employee, {
                    **target,
                    "ippis_number": rec["ippis_number"],
                    "file_no": rec["file_no"] if rec["file_no"] is not None else 0,  # Cannot be null
                    "serial_no": rec["serial_no"],
                }))
                continue
            if rec["file_no"] is not None:
                target["file_no"] = rec["file_no"]
            if rec["serial_no"] is not None:
                target["serial_no"] = rec["serial_no"]
            if any(current.get(k) != v for k, v in target.items()):
                updates.append(fit(Employee, {"id": current["id"], **target}))
            if any(current.get(k) != target[k] for k in ("gl", "department", "division")):
                history.append(fit(EmployeeHistory, {
                    "employee_id": current["id"], "batch_id": batch_id,
                    "old_gl": current.get("gl"), "old_department": current.get("department"),
                    "old_division": current.get("division"),
                    "new_gl": target["gl"], "new_department": target["department"],
                    "new_division": target["division"],
                }))

        created = []
        if new_rows:
            created = db.session.execute(
                insert(Employee).returning(Employee.id, Employee.ippis_number), new_rows
            ).all()
        if updates:
            db.session.execute(update(Employee), updates)
        if history:
            db.session.execute(insert(EmployeeHistory), history)

        def on_success():
            for row in new_rows:
                known[row["ippis_number"]] = dict(row)
            for emp_id, ippis in created:
                known[ippis]["id"] = emp_id
            for upd in updates:
                for rec in known.values():
                    if rec.get("id") == upd["id"]:
                        rec.update(upd)
                        break
        return on_success

    return write_in_chunks(list(by_ippis.values()), write_chunk, progress)


# ── Payslips ─────────────────────────────────────────────────────────────────

def save_payslips(payslips, month_year, batch_id, progress=None):
    """
    Create or replace one month's payslips (with their earnings and deductions).
    payslips: parsed page data (see pdf_parser._parse_page_text) with 'pdf_page_num'.
    """
    employees = {
        row.ippis_number: dict(row._mapping)
        for row in db.session.execute(db.select(
            Employee.id, Employee.ippis_number, Employee.gl, Employee.department, Employee.division,
        ))
    }
    existing = dict(db.session.execute(
        db.select(Payslip.employee_id, Payslip.id).where(Payslip.month_year == month_year)
    ).all())
    # The last page wins when an IPPIS number appears twice
    by_ippis = {p["ippis_number"]: p for p in payslips}

    def write_chunk(chunk):
        # 1. Employees not on record yet get a minimal record
        missing = [p for p in chunk if p["ippis_number"] not in employees]
        created = {}
        if missing:
            rows = db.session.execute(
                insert(Employee).returning(Employee.id, Employee.ippis_number),
                [fit(Employee, {
                    "ippis_number": p["ippis_number"], "name": p.get("name") or "Unknown",
                    "file_no": 0, "gl": normalize_gl(p.get("grade")),
                }) for p in missing],
            ).all()
            created = {ippis: emp_id for emp_id, ippis in rows}

        def employee_id(p):
            known = employees.get(p["ippis_number"])
            return known["id"] if known else created[p["ippis_number"]]

        # 2. Keep each employee's GL in line with their latest payslip
        gl_updates = []
        for p in chunk:
            known = employees.get(p["ippis_number"])
            gl = normalize_gl(p.get("grade"))
            if known and gl and known.get("gl") != gl:
                gl_updates.append({"id": known["id"], "gl": gl})
        if gl_updates:
            db.session.execute(update(Employee), gl_updates)

        # 3. Payslips: replace this month's existing ones, add the rest
        new_rows, replace_rows = [], []
        for p in chunk:
            emp_id = employee_id(p)
            known = employees.get(p["ippis_number"]) or {}
            values = fit(Payslip, {
                **{f: p.get(f) for f in PAYSLIP_FIELDS},
                "batch_id": batch_id,
                # Where the employee was this month, frozen for past-month reports
                "department": known.get("department"),
                "division": known.get("division"),
                "gl": normalize_gl(p.get("grade")),
            })
            if emp_id in existing:
                replace_rows.append({"id": existing[emp_id], **values})
            else:
                new_rows.append({"employee_id": emp_id, "month_year": month_year, **values})

        payslip_ids = {}
        if replace_rows:
            db.session.execute(update(Payslip), replace_rows)
            ids = [r["id"] for r in replace_rows]
            db.session.execute(delete(PayslipEarning).where(PayslipEarning.payslip_id.in_(ids)),
                               execution_options={"synchronize_session": False})
            db.session.execute(delete(PayslipDeduction).where(PayslipDeduction.payslip_id.in_(ids)),
                               execution_options={"synchronize_session": False})
        inserted = []
        if new_rows:
            inserted = db.session.execute(
                insert(Payslip).returning(Payslip.id, Payslip.employee_id), new_rows
            ).all()
        new_ids = {emp: pid for pid, emp in inserted}
        for p in chunk:
            emp_id = employee_id(p)
            payslip_ids[p["ippis_number"]] = existing.get(emp_id) or new_ids[emp_id]

        # 4. Earnings and deductions
        earnings = [fit(PayslipEarning, {"payslip_id": payslip_ids[p["ippis_number"]],
                                         "earning_type": e["type"], "amount": e["amount"]})
                    for p in chunk for e in p.get("earnings", [])]
        deductions = [fit(PayslipDeduction, {"payslip_id": payslip_ids[p["ippis_number"]],
                                             "deduction_type": d["type"], "amount": d["amount"]})
                      for p in chunk for d in p.get("deductions", [])]
        if earnings:
            db.session.execute(insert(PayslipEarning), earnings)
        if deductions:
            db.session.execute(insert(PayslipDeduction), deductions)

        def on_success():
            for ippis, emp_id in created.items():
                p = by_ippis[ippis]
                employees[ippis] = {"id": emp_id, "ippis_number": ippis, "gl": normalize_gl(p.get("grade")),
                                    "department": None, "division": None}
            for upd in gl_updates:
                for rec in employees.values():
                    if rec["id"] == upd["id"]:
                        rec["gl"] = upd["gl"]
                        break
            existing.update({emp: pid for emp, pid in new_ids.items()})
        return on_success

    return write_in_chunks(list(by_ippis.values()), write_chunk, progress)
