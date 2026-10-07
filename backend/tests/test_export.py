import io
import os
import zipfile

import fitz
import pytest

from app.models.employee import Employee
from app.models.payslip import Payslip
from app.models.upload_batch import UploadBatch

MONTH = "2026-08"


def _make_pdf(path, labels):
    """Write a PDF with one page per label, each page containing its label as text."""
    doc = fitz.open()
    for label in labels:
        doc.new_page().insert_text((72, 72), label)
    doc.save(path)
    doc.close()


def _page_texts(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return [page.get_text().strip() for page in doc]


@pytest.fixture
def payroll(app, db_session, tmp_path):
    """Two months of payslips for four employees across two departments (plus one unassigned)."""
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    app.config["SUPABASE_URL"] = None
    app.config["SUPABASE_KEY"] = None

    staff = [
        # name, department, gl, ippis
        ("Zara", "ROLLING MILLS", "04", 1),
        ("Adam", "ROLLING MILLS", "05", 2),
        ("Musa", "ROLLING MILL", "04", 3),
        ("Bola", None, "04", 4),
    ]
    employees = {}
    for name, department, gl, ippis in staff:
        emp = Employee(file_no=ippis, ippis_number=ippis, name=name, department=department, gl=gl)
        db_session.add(emp)
        employees[name] = emp
    db_session.flush()

    for month in (MONTH, "2026-07"):
        os.makedirs(tmp_path / month)
        filename = f"payslips_{month}.pdf"
        _make_pdf(str(tmp_path / month / filename), [f"{name} {month}" for name, *_ in staff])
        batch = UploadBatch(month_year=month, pdf_filename=filename, status="completed")
        db_session.add(batch)
        db_session.flush()
        for page_num, (name, *_) in enumerate(staff):
            db_session.add(Payslip(
                employee_id=employees[name].id, batch_id=batch.id, month_year=month, pdf_page_num=page_num,
            ))
    db_session.commit()
    return employees


def test_bulk_pdf_requires_auth(client):
    assert client.get(f"/api/export/bulk-payslips?month_year={MONTH}").status_code == 401


def test_bulk_pdf_for_month_is_sorted_by_name(client, auth_headers, payroll):
    res = client.get(f"/api/export/bulk-payslips?month_year={MONTH}", headers=auth_headers)
    assert res.status_code == 200
    assert res.mimetype == "application/pdf"
    assert _page_texts(res.data) == [f"{n} {MONTH}" for n in ("Adam", "Bola", "Musa", "Zara")]


def test_bulk_pdf_department_filter_is_exact(client, auth_headers, payroll):
    """'ROLLING MILL' must not pull in 'ROLLING MILLS' staff, and matching ignores case."""
    res = client.get(
        "/api/export/bulk-payslips",
        query_string={"month_year": MONTH, "department": "rolling mills"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert _page_texts(res.data) == [f"Adam {MONTH}", f"Zara {MONTH}"]
    assert "Payslips_rolling_mills_2026_08.pdf" in res.headers["Content-Disposition"]

    res = client.get(
        "/api/export/bulk-payslips",
        query_string={"month_year": MONTH, "department": "ROLLING MILL"},
        headers=auth_headers,
    )
    assert _page_texts(res.data) == [f"Musa {MONTH}"]


def test_bulk_pdf_gl_and_search_filters(client, auth_headers, payroll):
    res = client.get(
        "/api/export/bulk-payslips",
        query_string={"month_year": MONTH, "department": "ROLLING MILLS", "gl": "04,06"},
        headers=auth_headers,
    )
    assert _page_texts(res.data) == [f"Zara {MONTH}"]

    res = client.get(
        "/api/export/bulk-payslips", query_string={"month_year": MONTH, "search": "mus"}, headers=auth_headers,
    )
    assert _page_texts(res.data) == [f"Musa {MONTH}"]


def test_bulk_pdf_errors(client, auth_headers, payroll, tmp_path):
    assert client.get("/api/export/bulk-payslips", headers=auth_headers).status_code == 400

    res = client.get("/api/export/bulk-payslips?month_year=2020-01", headers=auth_headers)
    assert res.status_code == 404

    # Original PDF gone from storage -> a clear JSON error, not a crash
    os.remove(tmp_path / MONTH / f"payslips_{MONTH}.pdf")
    res = client.get(f"/api/export/bulk-payslips?month_year={MONTH}", headers=auth_headers)
    assert res.status_code == 404
    assert "Re-upload" in res.get_json()["error"]


def test_department_summary(client, auth_headers, payroll):
    res = client.get(f"/api/export/department-payslips?month_year={MONTH}", headers=auth_headers)
    assert res.status_code == 200
    rows = {d["label"]: d for d in res.get_json()["departments"]}
    assert {label: d["payslips"] for label, d in rows.items()} == {
        "ROLLING MILLS": 2, "ROLLING MILL": 1, "Unassigned": 1,
    }

    # The value returned for unassigned staff can be fed straight back as a filter
    res = client.get(
        "/api/export/bulk-payslips",
        query_string={"month_year": MONTH, "department": rows["Unassigned"]["department"]},
        headers=auth_headers,
    )
    assert _page_texts(res.data) == [f"Bola {MONTH}"]


def test_department_zip_has_one_pdf_per_department(client, auth_headers, payroll):
    res = client.get(f"/api/export/department-payslips/zip?month_year={MONTH}", headers=auth_headers)
    assert res.status_code == 200
    assert res.mimetype == "application/zip"

    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        contents = {name: _page_texts(zf.read(name)) for name in zf.namelist()}
    assert contents == {
        "ROLLING_MILLS_2026_08.pdf": [f"Adam {MONTH}", f"Zara {MONTH}"],
        "ROLLING_MILL_2026_08.pdf": [f"Musa {MONTH}"],
        "Unassigned_2026_08.pdf": [f"Bola {MONTH}"],
    }


def test_employee_bulk_pdf_spans_months(client, auth_headers, payroll):
    """Regression: 'View All Filtered' on the employee page merges pages from several monthly PDFs."""
    adam = payroll["Adam"]
    res = client.get(f"/api/export/employee-bulk-payslips?employee_id={adam.id}", headers=auth_headers)
    assert res.status_code == 200
    assert _page_texts(res.data) == ["Adam 2026-07", f"Adam {MONTH}"]

    august = Payslip.query.filter_by(employee_id=adam.id, month_year=MONTH).one()
    res = client.get(
        "/api/export/employee-bulk-payslips",
        query_string={"employee_id": adam.id, "payslip_ids": str(august.id)},
        headers=auth_headers,
    )
    assert _page_texts(res.data) == [f"Adam {MONTH}"]

    res = client.get(
        "/api/export/employee-bulk-payslips",
        query_string={"employee_id": adam.id, "payslip_ids": "abc"},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_single_payslip_pdf(client, auth_headers, payroll):
    zara = Payslip.query.filter_by(employee_id=payroll["Zara"].id, month_year=MONTH).one()
    res = client.get(f"/api/payslips/{zara.id}/pdf", headers=auth_headers)
    assert res.status_code == 200
    assert _page_texts(res.data) == [f"Zara {MONTH}"]


def test_employee_list_and_csv_share_filters(client, auth_headers, payroll):
    res = client.get("/api/employees", query_string={"department": "ROLLING MILL"}, headers=auth_headers)
    assert [e["name"] for e in res.get_json()["employees"]] == ["Musa"]

    # Multi-select GL used to return an empty CSV
    res = client.get("/api/export/employees", query_string={"gl": "04,05"}, headers=auth_headers)
    assert res.data.decode().count("\n") == 5  # header + 4 employees

    # Unknown sort fields fall back to name instead of crashing
    res = client.get("/api/employees?sort_by=query", headers=auth_headers)
    assert res.status_code == 200


def _payslip_pdf_bytes(*lines):
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + 20 * i), line)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def upload_env(app, tmp_path, monkeypatch):
    """Uploads go to a temp folder and the background parsing step is skipped."""
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    monkeypatch.setattr("app.routes.upload._process_upload", lambda *args: None)
    return tmp_path


def test_upload_reads_month_from_pdf(client, auth_headers, upload_env):
    """No month is sent: it is taken from the text of the payslips."""
    pdf = _payslip_pdf_bytes("Payslip for August 2026", "IPPIS Number: 641215")
    res = client.post(
        "/api/upload",
        data={"pdf_file": (io.BytesIO(pdf), "AJAOKUTA payslips.pdf")},
        headers=auth_headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 202
    batch = res.get_json()["batch"]
    assert batch["month_year"] == "2026-08"
    assert os.listdir(upload_env) == ["2026-08"]
    assert os.listdir(upload_env / "2026-08") == [batch["pdf_filename"]]


def test_upload_pdf_month_overrides_client_value(client, auth_headers, upload_env):
    pdf = _payslip_pdf_bytes("Payslip for August 2026", "IPPIS Number: 641215")
    res = client.post(
        "/api/upload",
        data={"month_year": "2026-07", "pdf_file": (io.BytesIO(pdf), "p.pdf")},
        headers=auth_headers,
        content_type="multipart/form-data",
    )
    assert res.get_json()["batch"]["month_year"] == "2026-08"


def test_upload_rejects_pdf_without_month(client, auth_headers, upload_env):
    for content in (_payslip_pdf_bytes("nothing useful here"), b"this is not a pdf"):
        res = client.post(
            "/api/upload",
            data={"pdf_file": (io.BytesIO(content), "p.pdf")},
            headers=auth_headers,
            content_type="multipart/form-data",
        )
        assert res.status_code == 400
    # Nothing is left behind from the rejected uploads
    assert os.listdir(upload_env) == []


def test_upload_rejects_bad_month(client, auth_headers):
    res = client.post(
        "/api/upload",
        data={"month_year": "../../etc", "pdf_file": (io.BytesIO(b"%PDF-1.4"), "x.pdf")},
        headers=auth_headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
