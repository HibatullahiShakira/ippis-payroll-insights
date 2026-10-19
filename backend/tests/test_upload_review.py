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
        data["excel_file"] = (io.BytesIO(excel), "roll.xlsx")
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
