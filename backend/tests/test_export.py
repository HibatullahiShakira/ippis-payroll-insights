import io
import os
import zipfile

import fitz
import pytest

from app.extensions import db
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
            emp = employees[name]
            db_session.add(Payslip(
                employee_id=emp.id, batch_id=batch.id, month_year=month, pdf_page_num=page_num,
                # As the importer does: where the employee was that month
                department=emp.department, division=emp.division, gl=emp.gl,
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
    """Uploads go to a temp folder and the background checking step is skipped."""
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    monkeypatch.setattr("app.routes.upload._analyze_upload", lambda *args: None)
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
    assert batch["status"] == "analyzing"
    # Held aside until confirmed: nothing lands in the month folder yet
    assert os.listdir(upload_env) == ["pending"]
    assert os.listdir(upload_env / "pending" / str(batch["id"])) == [batch["pdf_filename"]]


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


def test_pdf_with_no_readable_payslips_fails_with_reason(app, db_session, tmp_path):
    """A PDF that yields no payslips must fail loudly instead of 'completing' with 0 records."""
    from app.services.pdf_parser import PdfParseError, parse_pdf

    path = tmp_path / "september.pdf"
    path.write_bytes(_payslip_pdf_bytes("EMPLOYEE PAYSLIP", "SEPTEMBER 2026", "no ippis here"))
    batch = UploadBatch(month_year="2026-09", pdf_filename="september.pdf", status="processing")
    db_session.add(batch)
    db_session.commit()

    with pytest.raises(PdfParseError, match="1 page\(s\) had no IPPIS Number"):
        parse_pdf(str(path), batch.id, "2026-09")


def test_normalize_gl():
    from app.utils import normalize_gl

    assert normalize_gl("GL14_CONPSS") == "14"
    assert normalize_gl("GL08_CONPSS") == "08"
    assert normalize_gl(8) == "08"
    assert normalize_gl("8") == "08"
    assert normalize_gl(" ") is None
    assert len(normalize_gl("SOMETHING VERY LONG")) <= 10


def test_line_items_on_separate_lines():
    """IPPIS payslip text puts each amount on the line after its description."""
    from decimal import Decimal
    from app.services.pdf_parser import _parse_line_items

    items = _parse_line_items("Pension\n20,713.33\nCtss Rent\nAja\n350\nNhf 6,472.92\nTotal\n27,536.25")
    assert items == [
        {"type": "Pension", "amount": Decimal("20713.33")},
        {"type": "Ctss Rent Aja", "amount": Decimal("350")},
        {"type": "Nhf", "amount": Decimal("6472.92")},
    ]


def test_payslip_upload_sets_short_gl_and_breakdown(app, db_session, tmp_path):
    """Regression: the full grade 'GL14_CONPSS' (11 chars) overflowed Employee.gl (10) and
    PostgreSQL rejected every page, so whole months uploaded as 0 records."""
    from app.services.pdf_parser import parse_pdf

    emp = Employee(file_no=1, ippis_number=128364, name="FAKAYEJO", gl=None)
    db_session.add(emp)
    batch = UploadBatch(month_year="2026-09", pdf_filename="sept.pdf", status="processing")
    db_session.add(batch)
    db_session.commit()

    text = (
        "EMPLOYEE PAYSLIP", "SEPTEMBER 2026", "Employee Name", "FAKAYEJO, Mrs. ANTHONIA", "Grade:", "GL14_CONPSS",
        "IPPIS Number:", "128364", "Gross Earnings Information", "Earnings", "Amount", "Conpss Cons Salary",
        "258,916.67", "Total", "258,916.67", "Gross Deductions Information", "Deductions", "Amount",
        "Pension", "20,713.33", "Total", "20,713.33",
    )
    path = tmp_path / "sept.pdf"
    path.write_bytes(_payslip_pdf_bytes(*text))

    assert parse_pdf(str(path), batch.id, "2026-09") == 1
    db_session.refresh(emp)
    assert emp.gl == "14"
    payslip = Payslip.query.filter_by(employee_id=emp.id).one()
    assert payslip.grade == "GL14_CONPSS"
    assert [e.earning_type for e in payslip.earnings] == ["Conpss Cons Salary"]
    assert [d.deduction_type for d in payslip.deductions] == ["Pension"]


def test_nominal_roll_without_gl_column_keeps_existing_gl(app, db_session, tmp_path):
    """A nominal roll with no GL column used to wipe every employee's GL."""
    import openpyxl
    from app.services.excel_parser import parse_excel

    db_session.add(Employee(file_no=5, ippis_number=777, name="OLD NAME", gl="12", department="POWER"))
    db_session.commit()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["S/NO", "FILE NO", "IPPIS NUMBER", "NAME", "DEPARTMENT"])
    ws.append([1, 5, 777, "NEW NAME", "ROLLING MILLS"])
    path = tmp_path / "roll.xlsx"
    wb.save(path)

    parse_excel(str(path))
    emp = Employee.query.filter_by(ippis_number=777).one()
    assert (emp.name, emp.gl, emp.department) == ("NEW NAME", "12", "ROLLING MILLS")


def test_past_months_keep_the_department_of_that_month(client, auth_headers, payroll, db_session):
    """Adam transfers to POWER after August: August reports still list him under ROLLING MILLS."""
    adam = payroll["Adam"]
    adam.department = "POWER"
    adam.gl = "06"
    db_session.commit()

    res = client.get(f"/api/export/department-payslips?month_year={MONTH}", headers=auth_headers)
    counts = {d["label"]: d["payslips"] for d in res.get_json()["departments"]}
    assert counts["ROLLING MILLS"] == 2
    assert "POWER" not in counts

    res = client.get(
        "/api/export/bulk-payslips",
        query_string={"month_year": MONTH, "department": "ROLLING MILLS", "gl": "05"},
        headers=auth_headers,
    )
    assert _page_texts(res.data) == [f"Adam {MONTH}"]

    res = client.get(f"/api/analytics/department-summary?month_year={MONTH}", headers=auth_headers)
    summary = {d["department"]: d["headcount"] for d in res.get_json()["departments"]}
    assert summary["ROLLING MILLS"] == 2


def test_schema_upgrade_adds_and_backfills_payslip_placement(app, db_session):
    """An existing database without the new columns gets them, filled from current records."""
    from sqlalchemy import inspect, text
    from app.schema import ensure_schema, reset_for_tests

    emp = Employee(file_no=1, ippis_number=1, name="A", department="POWER", division="GRID")
    db_session.add(emp)
    batch = UploadBatch(month_year=MONTH, status="completed")
    db_session.add(batch)
    db_session.commit()
    db_session.add(Payslip(employee_id=emp.id, batch_id=batch.id, month_year=MONTH, grade="GL08_CONPSS"))
    db_session.commit()

    # Recreate the old table shape: drop the new columns
    with db.engine.begin() as conn:
        for column in ("department", "division", "gl"):
            conn.execute(text(f"DROP INDEX IF EXISTS ix_payslips_{column}"))
            conn.execute(text(f"ALTER TABLE payslips DROP COLUMN {column}"))
    assert "department" not in {c["name"] for c in inspect(db.engine).get_columns("payslips")}

    reset_for_tests()
    ensure_schema()
    ensure_schema()  # safe to run again

    row = db.session.execute(text("SELECT department, division, gl FROM payslips")).one()
    assert tuple(row) == ("POWER", "GRID", "08")


def test_history_cleanup_script(app, db_session, capsys):
    from app.models.employee_history import EmployeeHistory as H
    from scripts.clean_employee_history import main

    wiped = Employee(file_no=1, ippis_number=11, name="WIPED", gl=None, department="POWER")
    moved = Employee(file_no=2, ippis_number=12, name="MOVED", gl=None, department="GRID")
    fmt = Employee(file_no=3, ippis_number=13, name="FORMAT", gl="8", department="POWER")
    flip = Employee(file_no=4, ippis_number=14, name="FLIP", gl="09", department="MD/CE", division="SECURITY")
    db_session.add_all([wiped, moved, fmt, flip])
    batch = UploadBatch(month_year=MONTH, status="completed")
    db_session.add(batch)
    db_session.flush()
    db_session.add_all([
        # GL and division blanked by a roll without those columns: no real change
        H(employee_id=wiped.id, old_gl="12", new_gl=None, old_department="POWER", new_department="POWER",
          old_division="GRID", new_division=None),
        # A real transfer recorded together with a blanked GL
        H(employee_id=moved.id, old_gl="10", new_gl=None, old_department="POWER", new_department="GRID"),
        # A real promotion, then a formatting-only "change"
        H(employee_id=fmt.id, old_gl="07", new_gl="08", old_department="POWER", new_department="POWER"),
        H(employee_id=fmt.id, old_gl="08", new_gl="8", old_department="POWER", new_department="POWER"),
        # August layout flip and its reversal in September
        H(employee_id=flip.id, old_gl="09", new_gl=None, old_department="MD/CE", new_department="SECURITY",
          old_division="SECURITY", new_division=None),
        H(employee_id=flip.id, old_gl=None, new_gl=None, old_department="SECURITY", new_department="MD/CE",
          old_division=None, new_division="SECURITY"),
        Payslip(employee_id=wiped.id, batch_id=batch.id, month_year=MONTH, grade="GL12_CONPSS"),
    ])
    db_session.commit()

    # Report only: nothing changes
    main([], app=app)
    out = capsys.readouterr().out
    assert "2 record no real change" in out
    assert "1 pairs where a change is exactly undone" in out
    assert H.query.count() == 6

    main(["--apply"], app=app)
    rows = lambda: [(h.employee_id, h.old_gl, h.new_gl, h.new_department) for h in H.query.order_by(H.id)]
    # Round trips are kept unless asked; the transfer keeps its GL; the real promotion stays
    assert rows() == [
        (moved.id, "10", "10", "GRID"),
        (fmt.id, "07", "08", "POWER"),
        (flip.id, "09", "09", "SECURITY"),
        (flip.id, "09", "09", "MD/CE"),
    ]
    # Running it again changes nothing more
    main(["--apply"], app=app)
    assert len(rows()) == 4
    db_session.expire_all()
    assert db.session.get(Employee, wiped.id).gl == "12"   # filled from the payslip
    assert db.session.get(Employee, fmt.id).gl == "08"     # two-digit form

    main(["--apply", "--remove-round-trips"], app=app)
    assert [r[0] for r in rows()] == [moved.id, fmt.id]
