"""Upload review flow: files are checked first, imported only after confirmation."""

import io
import os
from datetime import datetime, timedelta, timezone

import fitz
import openpyxl
import pytest

from app.extensions import db
from app.models.employee import Employee
from app.models.payslip import Payslip
from app.models.upload_batch import UploadBatch


def payslip_lines(ippis, name, month="SEPTEMBER 2026", gross="300,000.00", deductions="50,000.00",
                  net="250,000.00", grade="GL12_CONPSS"):
    return [
        "EMPLOYEE PAYSLIP", month, "Employee Name", name, "Grade:", grade, "IPPIS Number:", str(ippis),
        "Total Gross Earnings", gross, "Total Gross Deductions", deductions, "Total Net Earnings:", net,
        "Gross Earnings Information", "Earnings", "Amount", "Basic Salary", gross, "Total", gross,
        "Gross Deductions Information", "Deductions", "Amount", "Pension", deductions, "Total", deductions,
    ]


def make_pdf(*pages):
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((40, 30 + 14 * i), line, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def make_xlsx(rows):
    wb = openpyxl.Workbook()
    for row in rows:
        wb.active.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.fixture
def env(app, tmp_path, monkeypatch):
    """Run the background steps inline so each request finishes its work before returning."""
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    app.config["SUPABASE_URL"] = None
    app.config["SUPABASE_KEY"] = None
    monkeypatch.setattr("app.routes.upload._start_background", lambda target, *args: target(app, *args))
    return tmp_path


def upload(client, headers, pdf=None, excel=None, pdf_name="sept.pdf", month_year=None):
    data = {"month_year": month_year} if month_year else {}
    if pdf is not None:
        data["pdf_file"] = (io.BytesIO(pdf), pdf_name)
    if excel is not None:
        data["excel_file"] = (io.BytesIO(excel), "NOMINAL ROLL SEP 2026.xlsx")
    res = client.post("/api/upload", data=data, headers=headers, content_type="multipart/form-data")
    assert res.status_code == 202, res.get_json()
    batch_id = res.get_json()["batch"]["id"]
    return client.get(f"/api/uploads/{batch_id}/status", headers=headers).get_json()


def levels(report):
    return {(c["level"], c["message"].split(".")[0]) for c in report["checks"]}


def test_upload_is_checked_then_imported_on_confirm(client, auth_headers, env):
    pdf = make_pdf(payslip_lines(1001, "ADA, Mrs. OBI"), payslip_lines(1002, "BELLO, Mr. SANI"), ["Confidential"])
    status = upload(client, auth_headers, pdf=pdf)

    assert status["batch"]["status"] == "awaiting_review"
    report = status["report"]
    assert report["can_import"] is True
    assert report["month_year"] == "2026-09"
    assert report["pdf"]["payslips"] == 2
    assert report["pdf"]["overflow_pages"] == 1
    assert ("ok", "Gross minus Deductions equals Net Pay on every payslip") in levels(report)
    # Nothing imported yet
    assert Payslip.query.count() == 0

    batch_id = status["batch"]["id"]
    res = client.post(f"/api/uploads/{batch_id}/confirm", headers=auth_headers)
    assert res.status_code == 202
    final = client.get(f"/api/uploads/{batch_id}/status", headers=auth_headers).get_json()["batch"]
    assert final["status"] == "completed"
    assert final["total_records"] == 2
    assert Payslip.query.filter_by(month_year="2026-09").count() == 2
    assert os.listdir(env / "2026-09") == ["sept.pdf"]
    assert not os.path.exists(env / "pending" / str(batch_id))

    # Cannot be imported twice
    assert client.post(f"/api/uploads/{batch_id}/confirm", headers=auth_headers).status_code == 409


def test_cancel_leaves_existing_month_untouched(client, auth_headers, env):
    month_dir = env / "2026-09"
    month_dir.mkdir()
    (month_dir / "sept.pdf").write_bytes(b"original month PDF")

    status = upload(client, auth_headers, pdf=make_pdf(payslip_lines(1001, "ADA, Mrs. OBI")))
    batch_id = status["batch"]["id"]
    res = client.post(f"/api/uploads/{batch_id}/cancel", headers=auth_headers)
    assert res.get_json()["batch"]["status"] == "cancelled"

    assert (month_dir / "sept.pdf").read_bytes() == b"original month PDF"
    assert not os.path.exists(env / "pending" / str(batch_id))
    assert Payslip.query.count() == 0


def test_pdf_without_payslips_cannot_be_imported(client, auth_headers, env):
    # e.g. a scanned PDF: no payslip text, month supplied by the caller
    status = upload(client, auth_headers, pdf=make_pdf(["nothing readable"]), month_year="2026-09")
    report = status["report"]
    assert report["can_import"] is False
    assert report["errors"] == 1
    res = client.post(f"/api/uploads/{status['batch']['id']}/confirm", headers=auth_headers)
    assert res.status_code == 409


def test_figures_that_do_not_add_up_are_flagged(client, auth_headers, env):
    pdf = make_pdf(payslip_lines(1001, "ADA, Mrs. OBI", net="240,000.00"))
    report = upload(client, auth_headers, pdf=pdf)["report"]
    assert report["can_import"] is True  # a warning, not a blocker
    assert any(c["level"] == "warning" and "does not equal Net Pay" in c["message"] for c in report["checks"])
    assert report["pdf"]["examples"][0]["ippis"] == 1001


def test_headcount_drop_is_flagged(client, auth_headers, env, db_session):
    batch = UploadBatch(month_year="2026-08", status="completed")
    db_session.add(batch)
    db_session.flush()
    for ippis in range(1, 21):
        emp = Employee(file_no=ippis, ippis_number=ippis, name=f"E{ippis}")
        db_session.add(emp)
        db_session.flush()
        db_session.add(Payslip(employee_id=emp.id, batch_id=batch.id, month_year="2026-08"))
    db_session.commit()

    pdf = make_pdf(*[payslip_lines(i, f"E{i}, Mr. X") for i in range(1, 11)])
    report = upload(client, auth_headers, pdf=pdf)["report"]
    assert report["pdf"]["previous_month"] == "2026-08"
    assert report["pdf"]["left"] == 10
    assert any(c["level"] == "warning" and c["message"].startswith("Headcount changed") for c in report["checks"])


def test_nominal_roll_column_checks(client, auth_headers, env):
    # Renamed headers are still recognised; a missing GL column is a warning, not data loss
    excel = make_xlsx([
        ["AJAOKUTA STEEL - NOMINAL ROLL"],
        ["SN", "IPPIS NO", "STAFF NAME", "DEPARTMENT NAME", "DESIGNATION"],
        [1, 1001, "ADA OBI", "POWER", "ENGINEER"],
        [2, None, "NO IPPIS", "POWER", "CLERK"],
    ])
    report = upload(client, auth_headers, excel=excel)["report"]
    assert report["can_import"] is True
    assert report["excel"]["header_row"] == 2
    assert report["excel"]["columns"] == {
        "S/No": "SN", "IPPIS Number": "IPPIS NO", "Name": "STAFF NAME", "Department": "DEPARTMENT NAME",
    }
    assert report["excel"]["unrecognised_columns"] == ["DESIGNATION"]
    assert report["excel"]["skipped_rows"] == 1
    messages = " ".join(c["message"] for c in report["checks"] if c["level"] == "warning")
    assert "No File No, GL / Grade Level, Division column found" in messages

    # A sheet without an IPPIS column cannot be imported
    bad = make_xlsx([["NAME", "DEPT"], ["ADA", "POWER"]])
    report = upload(client, auth_headers, excel=bad)["report"]
    assert report["can_import"] is False


def test_stale_upload_is_marked_failed(client, auth_headers, env, db_session):
    batch = UploadBatch(
        month_year="2026-09", status="analyzing",
        uploaded_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db_session.add(batch)
    db_session.commit()
    res = client.get(f"/api/uploads/{batch.id}/status", headers=auth_headers).get_json()
    assert res["batch"]["status"] == "failed"
    assert "restarted" in res["batch"]["error_message"]


def _imported_month(client, headers, env, pdf, filed_under=None):
    """Upload and confirm a PDF, optionally pretending it was filed under another month (older uploads)."""
    status = upload(client, headers, pdf=pdf)
    batch_id = status["batch"]["id"]
    client.post(f"/api/uploads/{batch_id}/confirm", headers=headers)
    batch = db.session.get(UploadBatch, batch_id)
    if filed_under:
        os.rename(env / batch.month_year, env / filed_under)
        batch.month_year = filed_under
        db.session.commit()
    return batch


def test_reprocess_reads_stored_pdf_again_after_review(client, auth_headers, env):
    original = _imported_month(client, auth_headers, env, make_pdf(payslip_lines(1001, "ADA, Mrs. OBI")))
    payslip = Payslip.query.one()
    # Simulate data imported by an older parser: no breakdown saved
    for item in list(payslip.earnings) + list(payslip.deductions):
        db.session.delete(item)
    db.session.commit()

    res = client.post(f"/api/uploads/{original.id}/reprocess", headers=auth_headers)
    assert res.status_code == 202
    new_id = res.get_json()["batch"]["id"]
    status = client.get(f"/api/uploads/{new_id}/status", headers=auth_headers).get_json()
    assert status["batch"]["status"] == "awaiting_review"
    assert status["report"]["pdf"]["payslips"] == 1
    assert any("will be replaced" in c["message"] for c in status["report"]["checks"])
    # Nothing changes until confirmed
    db.session.expire_all()
    assert Payslip.query.one().earnings == []

    client.post(f"/api/uploads/{new_id}/confirm", headers=auth_headers)
    db.session.expire_all()
    payslip = Payslip.query.one()
    assert [e.earning_type for e in payslip.earnings] == ["Basic Salary"]
    assert [d.deduction_type for d in payslip.deductions] == ["Pension"]


def test_reprocess_uses_the_month_printed_on_the_payslips(client, auth_headers, env):
    """An old upload filed under the wrong month is re-read under the right one."""
    original = _imported_month(client, auth_headers, env, make_pdf(payslip_lines(1001, "ADA, Mrs. OBI")),
                               filed_under="2026-07")
    res = client.post(f"/api/uploads/{original.id}/reprocess", headers=auth_headers)
    assert res.get_json()["batch"]["month_year"] == "2026-09"


def test_reprocess_needs_the_stored_pdf(client, auth_headers, env):
    original = _imported_month(client, auth_headers, env, make_pdf(payslip_lines(1001, "ADA, Mrs. OBI")))
    os.remove(env / "2026-09" / "sept.pdf")
    res = client.post(f"/api/uploads/{original.id}/reprocess", headers=auth_headers)
    assert res.status_code == 404
    assert "no longer stored" in res.get_json()["error"]

    # Uploads that never completed cannot be re-processed
    pending = upload(client, auth_headers, pdf=make_pdf(payslip_lines(1002, "BELLO, Mr. SANI")))
    res = client.post(f"/api/uploads/{pending['batch']['id']}/reprocess", headers=auth_headers)
    assert res.status_code == 409


def test_file_number_in_ippis_column_updates_the_right_employee(client, auth_headers, env, db_session):
    """
    Regression: the August roll had File Numbers in the IPPIS column for new staff,
    which created ~90 duplicate employees (wrong IPPIS, no File No, no GL).
    """
    db_session.add(Employee(ippis_number=641215, file_no=18155, name="ABAH CALEB ABAH", gl="09",
                            department="WATER & GAS FACILITIES"))
    db_session.commit()

    excel = make_xlsx([
        ["SN", "IPPIS NUMBER", "NAME", "DEPT"],
        [1, 18155, "ABAH  CALEB ABAH ", "ENGINEERING WORKS"],   # File No in the IPPIS column
        [2, 18299, "NEW PERSON NO PAYSLIP", "POWER"],          # short number, nobody to match
    ])
    status = upload(client, auth_headers, excel=excel)
    warnings = " ".join(c["message"] for c in status["report"]["checks"] if c["level"] == "warning")
    assert "1 row(s) have the File No in the IPPIS column" in warnings
    assert "ABAH  CALEB ABAH (18155 -> IPPIS 641215)" in warnings
    assert "1 new row(s) have a 5-digit-or-shorter IPPIS number" in warnings
    assert status["report"]["excel"]["new_employees"] == 1

    client.post(f"/api/uploads/{status['batch']['id']}/confirm", headers=auth_headers)
    db.session.expire_all()
    abah = Employee.query.filter(Employee.name.like("ABAH%")).all()
    assert len(abah) == 1                                   # no duplicate
    assert (abah[0].ippis_number, abah[0].file_no, abah[0].department, abah[0].gl) == (
        641215, 18155, "ENGINEERING WORKS", "09")
    assert Employee.query.count() == 2


def _import_roll(client, headers, filename, rows):
    excel = make_xlsx([["SN", "IPPIS NUMBER", "NAME", "DEPT"]] + rows)
    res = client.post("/api/upload", data={"excel_file": (io.BytesIO(excel), filename)}, headers=headers,
                      content_type="multipart/form-data")
    batch_id = res.get_json()["batch"]["id"]
    status = client.get(f"/api/uploads/{batch_id}/status", headers=headers).get_json()
    return batch_id, status


def _staff(n, dept):
    return [[i, 700000 + i, f"STAFF {chr(65 + i)} PERSON", dept] for i in range(n)]


def test_older_nominal_roll_is_blocked_after_a_newer_one(client, auth_headers, env):
    batch_id, status = _import_roll(client, auth_headers, "SEP2026 NOMINAL.xlsx", _staff(3, "MD/CE"))
    assert status["batch"]["month_year"] == "2026-09"   # month taken from the file name
    client.post(f"/api/uploads/{batch_id}/confirm", headers=auth_headers)

    _, status = _import_roll(client, auth_headers, "NOMINAL ROLL AUG 2026(FIN).xlsx", _staff(3, "SECURITY"))
    report = status["report"]
    assert report["can_import"] is False
    assert any(c["level"] == "error" and "This is the August 2026 nominal roll, but the September 2026 roll"
               in c["message"] for c in report["checks"])

    # Each month's roll is imported once: the same month again is blocked too
    _, status = _import_roll(client, auth_headers, "SEP2026 NOMINAL (2).xlsx", _staff(3, "MD/CE"))
    assert status["report"]["can_import"] is False
    assert any("September 2026 nominal roll was already imported" in c["message"] for c in status["report"]["checks"])

    # ...and a roll whose month cannot be read is blocked, since it cannot be checked
    _, status = _import_roll(client, auth_headers, "nominal roll.xlsx", _staff(3, "MD/CE"))
    assert status["report"]["can_import"] is False

    # A new month is fine
    _, status = _import_roll(client, auth_headers, "NOMINAL ROLL OCT 2026.xlsx", _staff(3, "MD/CE"))
    assert status["report"]["can_import"] is True


def test_nominal_roll_must_match_its_payslips_month(client, auth_headers, env):
    """Upload #42 paired the August roll with the October payslips."""
    excel = make_xlsx([["SN", "IPPIS NUMBER", "NAME", "DEPT"], [1, 1001, "ADA OBI", "POWER"]])
    pdf = make_pdf(payslip_lines(1001, "ADA, Mrs. OBI", month="OCTOBER 2026"))
    res = client.post("/api/upload", headers=auth_headers, content_type="multipart/form-data", data={
        "pdf_file": (io.BytesIO(pdf), "OCTOBER_2026.pdf"),
        "excel_file": (io.BytesIO(excel), "NOMINAL_ROLL_AUG_2026FIN-1.xlsx"),
    })
    report = client.get(f"/api/uploads/{res.get_json()['batch']['id']}/status", headers=auth_headers).get_json()["report"]
    assert report["can_import"] is False
    assert any("is for August 2026 (from its file name) but the payslips are for October 2026" in c["message"]
               for c in report["checks"])


def test_roll_that_moves_staff_back_is_flagged(client, auth_headers, env):
    """Catches an old roll's contents even when it is given a new month's file name."""
    batch_id, _ = _import_roll(client, auth_headers, "NOMINAL ROLL JAN 2026.xlsx", _staff(12, "SECURITY"))
    client.post(f"/api/uploads/{batch_id}/confirm", headers=auth_headers)
    batch_id, status = _import_roll(client, auth_headers, "NOMINAL ROLL FEB 2026.xlsx", _staff(12, "MD/CE"))
    assert status["report"]["excel"]["placement_changes"] == 12
    assert status["report"]["excel"]["placement_reversals"] == 0      # a normal set of moves
    client.post(f"/api/uploads/{batch_id}/confirm", headers=auth_headers)

    # Uploading the first roll again would undo every move
    _, status = _import_roll(client, auth_headers, "NOMINAL ROLL MAR 2026.xlsx", _staff(12, "SECURITY"))
    report = status["report"]
    assert report["excel"]["placement_reversals"] == 12
    assert any(c["level"] == "warning" and "would move staff BACK" in c["message"] for c in report["checks"])
    assert report["can_import"] is True   # a warning: correcting a mistake must stay possible


def test_payslip_month_already_uploaded_is_blocked_but_reprocess_works(client, auth_headers, env):
    pdf = make_pdf(payslip_lines(1001, "ADA, Mrs. OBI"))
    first = upload(client, auth_headers, pdf=pdf)
    client.post(f"/api/uploads/{first['batch']['id']}/confirm", headers=auth_headers)

    again = upload(client, auth_headers, pdf=pdf, pdf_name="sept again.pdf")
    assert again["report"]["can_import"] is False
    assert any("September 2026 payslips are already in the system" in c["message"] for c in again["report"]["checks"])

    # Re-process re-reads the stored file and is allowed
    res = client.post(f"/api/uploads/{first['batch']['id']}/reprocess", headers=auth_headers)
    status = client.get(f"/api/uploads/{res.get_json()['batch']['id']}/status", headers=auth_headers).get_json()
    assert status["report"]["can_import"] is True


def test_admin_delete_month_allows_a_fresh_upload(client, auth_headers, env):
    pdf = make_pdf(payslip_lines(1001, "ADA, Mrs. OBI"))
    excel = make_xlsx([["SN", "IPPIS NUMBER", "NAME", "DEPT"], [1, 1001, "ADA OBI", "POWER"]])
    first = upload(client, auth_headers, pdf=pdf, excel=excel)
    client.post(f"/api/uploads/{first['batch']['id']}/confirm", headers=auth_headers)
    assert upload(client, auth_headers, pdf=pdf, excel=excel)["report"]["can_import"] is False

    res = client.delete("/api/uploads/month/2026-09", headers=auth_headers)
    assert res.status_code == 200
    assert Payslip.query.count() == 0
    assert upload(client, auth_headers, pdf=pdf, excel=excel)["report"]["can_import"] is True
