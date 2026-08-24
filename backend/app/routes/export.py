"""Export routes — CSV download of filtered employee/payslip data."""

import io
import csv
from flask import Blueprint, request, Response, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from ..models.employee import Employee
from ..models.payslip import Payslip
from ..extensions import db

export_bp = Blueprint("export", __name__)


@export_bp.route("/export/employees", methods=["GET"])
@jwt_required()
def export_employees_csv():
    """Export filtered employee list as CSV."""
    query = Employee.query

    # Apply same filters as employee list endpoint
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(
            or_(
                Employee.name.ilike(f"%{search}%"),
                Employee.file_no.cast(db.String).like(f"%{search}%"),
                Employee.ippis_number.cast(db.String).like(f"%{search}%"),
            )
        )

    department = request.args.get("department", "").strip()
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    division = request.args.get("division", "").strip()
    if division:
        query = query.filter(Employee.division.ilike(f"%{division}%"))

    gl = request.args.get("gl", "").strip()
    if gl:
        query = query.filter(Employee.gl == gl)

    employees = query.order_by(Employee.name).all()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["S/NO", "File No", "IPPIS Number", "Name", "GL", "Department", "Division"])

    for i, emp in enumerate(employees, 1):
        writer.writerow([i, emp.file_no, emp.ippis_number, emp.name, emp.gl, emp.department, emp.division])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=employees_export.csv"},
    )


@export_bp.route("/export/payslips", methods=["GET"])
@jwt_required()
def export_payslips_csv():
    """Export payslip data as CSV for a given month."""
    month_year = request.args.get("month_year")

    query = Payslip.query.join(Employee)

    if month_year:
        query = query.filter(Payslip.month_year == month_year)

    department = request.args.get("department", "").strip()
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    gl = request.args.get("gl", "").strip()
    if gl:
        query = query.filter(Employee.gl == gl)

    payslips = query.order_by(Employee.name).all()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "S/NO", "Name", "IPPIS Number", "File No", "Department", "Division", "GL",
        "Grade", "Designation", "Month",
        "Gross Earnings", "Gross Deductions", "Net Earnings",
        "Bank Name", "Account Number",
    ])

    for i, p in enumerate(payslips, 1):
        emp = p.employee
        writer.writerow([
            i,
            emp.name if emp else "",
            emp.ippis_number if emp else "",
            emp.file_no if emp else "",
            emp.department if emp else "",
            emp.division if emp else "",
            emp.gl if emp else "",
            p.grade or "",
            p.designation or "",
            p.month_year,
            float(p.total_gross_earnings or 0),
            float(p.total_gross_deductions or 0),
            float(p.total_net_earnings or 0),
            p.bank_name or "",
            p.account_number or "",
        ])

    csv_data = output.getvalue()
    output.close()

    filename = f"payslips_export_{month_year or 'all'}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@export_bp.route("/export/bulk-payslips", methods=["GET"])
@jwt_required()
def export_bulk_payslips_pdf():
    """Export a single merged PDF of payslips for given filters."""
    month_year = request.args.get("month_year")
    if not month_year:
        return jsonify({"error": "month_year is required"}), 400

    query = Payslip.query.join(Employee).filter(Payslip.month_year == month_year)

    department = request.args.get("department", "").strip()
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    division = request.args.get("division", "").strip()
    if division:
        query = query.filter(Employee.division.ilike(f"%{division}%"))

    gl = request.args.get("gl", "").strip()
    if gl:
        gl_list = [g.strip() for g in gl.split(",") if g.strip()]
        if gl_list:
            query = query.filter(Employee.gl.in_(gl_list))

    payslips = query.order_by(Employee.name).all()

    if not payslips:
        return jsonify({"error": "No payslips found for given criteria."}), 404

    from ..models.upload_batch import UploadBatch
    from ..extensions import get_supabase
    import fitz  # PyMuPDF
    from flask import current_app
    import os

    merged_doc = fitz.open()
    supabase = get_supabase()

    # We need to fetch the original PDFs. We can cache them by batch_id to avoid downloading the same PDF multiple times
    batch_cache = {}

    try:
        for payslip in payslips:
            if payslip.pdf_page_num is None:
                continue

            batch_id = payslip.batch_id
            if batch_id not in batch_cache:
                batch = UploadBatch.query.get(batch_id)
                if not batch or not batch.pdf_filename:
                    continue

                storage_path = f"{batch.month_year}/{batch.pdf_filename}"
                pdf_bytes = io.BytesIO()

                if supabase:
                    try:
                        # Use requests directly to avoid supabase-py httpx 5s timeout
                        import requests
                        import tempfile
                        url = current_app.config.get("SUPABASE_URL")
                        key = current_app.config.get("SUPABASE_KEY")
                        download_url = f"{url}/storage/v1/object/authenticated/payslips/{storage_path}"
                        headers = {"Authorization": f"Bearer {key}", "apikey": key}
                        
                        dl_res = requests.get(download_url, headers=headers, stream=True, timeout=120)
                        dl_res.raise_for_status()
                        
                        # Save to a temporary file to save memory (memory-mapped by fitz)
                        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
                        with os.fdopen(fd, 'wb') as f:
                            for chunk in dl_res.iter_content(chunk_size=8192):
                                f.write(chunk)
                                
                        batch_cache[batch_id] = fitz.open(tmp_path)
                    except Exception as e:
                        current_app.logger.error(f"Failed to download from cloud: {e}")
                        continue
                else:
                    pdf_path = os.path.join(current_app.config["UPLOAD_FOLDER"], batch.month_year, batch.pdf_filename)
                    if os.path.exists(pdf_path):
                        with open(pdf_path, 'rb') as f:
                            pdf_bytes.write(f.read())
                        pdf_bytes.seek(0)
                        batch_cache[batch_id] = fitz.open(stream=pdf_bytes.read(), filetype="pdf")

            source_doc = batch_cache.get(batch_id)
            if source_doc and payslip.pdf_page_num < source_doc.page_count:
                merged_doc.insert_pdf(source_doc, from_page=payslip.pdf_page_num, to_page=payslip.pdf_page_num)

        if merged_doc.page_count == 0:
            return jsonify({"error": "Failed to generate any valid pages."}), 404

        out_bytes = io.BytesIO(merged_doc.write())
        out_bytes.seek(0)

        filename = f"Bulk_Payslips_{month_year}.pdf"
        return Response(
            out_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to generate bulk PDF: {str(e)}"}), 500


@export_bp.route("/export/employee-bulk-payslips", methods=["GET"])
@jwt_required()
def export_employee_bulk_payslips_pdf():
    """Export a single merged PDF of payslips for a specific employee."""
    employee_id = request.args.get("employee_id")
    payslip_ids_str = request.args.get("payslip_ids", "")

    if not employee_id:
        return jsonify({"error": "employee_id is required"}), 400

    query = Payslip.query.filter(Payslip.employee_id == employee_id)

    if payslip_ids_str:
        payslip_ids = [int(x.strip()) for x in payslip_ids_str.split(",") if x.strip()]
        if payslip_ids:
            query = query.filter(Payslip.id.in_(payslip_ids))

    payslips = query.order_by(Payslip.id).all()

    if not payslips:
        return jsonify({"error": "No payslips found for this employee."}), 404

    from ..models.upload_batch import UploadBatch
    from ..extensions import get_supabase
    import fitz  # PyMuPDF
    from flask import current_app
    import os

    merged_doc = fitz.open()
    supabase = get_supabase()
    batch_cache = {}

    try:
        for payslip in payslips:
            if payslip.pdf_page_num is None:
                continue

            batch_id = payslip.batch_id
            if batch_id not in batch_cache:
                batch = UploadBatch.query.get(batch_id)
                if not batch or not batch.pdf_filename:
                    continue

                storage_path = f"{batch.month_year}/{batch.pdf_filename}"
                pdf_bytes = io.BytesIO()

                if supabase:
                    try:
                        res = supabase.storage.from_("payslips").download(storage_path)
                        pdf_bytes.write(res)
                        pdf_bytes.seek(0)
                        batch_cache[batch_id] = fitz.open(stream=pdf_bytes.read(), filetype="pdf")
                    except Exception as e:
                        current_app.logger.error(f"Failed to download from cloud: {e}")
                        continue
                else:
                    pdf_path = os.path.join(current_app.config["UPLOAD_FOLDER"], batch.month_year, batch.pdf_filename)
                    if os.path.exists(pdf_path):
                        with open(pdf_path, 'rb') as f:
                            pdf_bytes.write(f.read())
                        pdf_bytes.seek(0)
                        batch_cache[batch_id] = fitz.open(stream=pdf_bytes.read(), filetype="pdf")

            source_doc = batch_cache.get(batch_id)
            if source_doc and payslip.pdf_page_num < source_doc.page_count:
                merged_doc.insert_pdf(source_doc, from_page=payslip.pdf_page_num, to_page=payslip.pdf_page_num)

        if merged_doc.page_count == 0:
            return jsonify({"error": "Failed to generate any valid pages."}), 404

        out_bytes = io.BytesIO(merged_doc.write())
        out_bytes.seek(0)

        filename = f"Employee_{employee_id}_Payslips.pdf"
        return Response(
            out_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to generate employee bulk PDF: {str(e)}"}), 500
