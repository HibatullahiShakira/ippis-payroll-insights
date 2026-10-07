"""Export routes — CSV and PDF downloads of filtered employee/payslip data."""

import io
import csv
import tempfile
import zipfile
from itertools import groupby

from flask import Blueprint, request, Response, jsonify, send_file, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import func
from sqlalchemy.orm import contains_eager, lazyload

from ..models.employee import Employee
from ..models.payslip import Payslip
from ..extensions import db
from ..services.pdf_export import PdfSources, merge_payslip_pages, safe_filename
from ..utils import UNASSIGNED, apply_employee_filters

export_bp = Blueprint("export", __name__)

NO_PAGES_ERROR = (
    "The original payslip PDF for this selection could not be retrieved. "
    "Re-upload the bulk PDF for the month and try again."
)


def _payslip_pages_query():
    """Base query yielding only what is needed to locate each payslip's PDF page."""
    return db.session.query(Payslip.batch_id, Payslip.pdf_page_num).join(
        Employee, Payslip.employee_id == Employee.id
    )


def _pdf_response(pdf_bytes, filename, as_attachment=True):
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=as_attachment,
        download_name=filename,
    )


@export_bp.route("/export/employees", methods=["GET"])
@jwt_required()
def export_employees_csv():
    """Export filtered employee list as CSV."""
    # Apply same filters as employee list endpoint
    query = apply_employee_filters(Employee.query, request.args)
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
    month_year = request.args.get("month_year", "").strip()

    # Earnings/deductions are not exported, so skip their (expensive) joined load
    query = Payslip.query.join(Employee).options(
        contains_eager(Payslip.employee),
        lazyload(Payslip.earnings),
        lazyload(Payslip.deductions),
    )

    if month_year:
        query = query.filter(Payslip.month_year == month_year)

    query = apply_employee_filters(query, request.args)
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

    filename = f"payslips_export_{safe_filename(month_year, 'all')}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@export_bp.route("/export/bulk-payslips", methods=["GET"])
@jwt_required()
def export_bulk_payslips_pdf():
    """Export a single merged PDF of payslips for a month, narrowed by the directory filters."""
    month_year = request.args.get("month_year", "").strip()
    if not month_year:
        return jsonify({"error": "month_year is required"}), 400

    query = _payslip_pages_query().filter(Payslip.month_year == month_year)
    query = apply_employee_filters(query, request.args)
    pages = query.order_by(Employee.name).all()

    if not pages:
        return jsonify({"error": "No payslips found for the selected month and filters."}), 404

    try:
        with PdfSources() as sources:
            pdf_bytes, _ = merge_payslip_pages(pages, sources)
    except Exception as e:
        current_app.logger.exception("Bulk payslip PDF export failed")
        return jsonify({"error": f"Failed to generate bulk PDF: {str(e)}"}), 500

    if pdf_bytes is None:
        return jsonify({"error": NO_PAGES_ERROR}), 404

    department = request.args.get("department", "").strip()
    if department:
        label = "Unassigned" if department == UNASSIGNED else safe_filename(department)
        filename = f"Payslips_{label}_{safe_filename(month_year)}.pdf"
    else:
        filename = f"Bulk_Payslips_{safe_filename(month_year)}.pdf"
    return _pdf_response(pdf_bytes, filename)


@export_bp.route("/export/department-payslips", methods=["GET"])
@jwt_required()
def department_payslips_summary():
    """List every department with the number of payslips it has for a month."""
    month_year = request.args.get("month_year", "").strip()
    if not month_year:
        return jsonify({"error": "month_year is required"}), 400

    department = func.nullif(Employee.department, "")
    rows = (
        db.session.query(
            department,
            func.count(Payslip.id),
            func.count(Payslip.pdf_page_num),
        )
        .join(Employee, Payslip.employee_id == Employee.id)
        .filter(Payslip.month_year == month_year)
        .group_by(department)
        .order_by(department)
        .all()
    )

    return jsonify({
        "month_year": month_year,
        "departments": [
            {
                "department": name or UNASSIGNED,
                "label": name or "Unassigned",
                "payslips": total,
                "pdf_pages": with_pdf,
            }
            for name, total, with_pdf in rows
        ],
    })


@export_bp.route("/export/department-payslips/zip", methods=["GET"])
@jwt_required()
def export_department_payslips_zip():
    """Export a ZIP holding one merged payslip PDF per department for a month."""
    month_year = request.args.get("month_year", "").strip()
    if not month_year:
        return jsonify({"error": "month_year is required"}), 400

    department = func.nullif(Employee.department, "")
    rows = (
        db.session.query(department, Payslip.batch_id, Payslip.pdf_page_num)
        .join(Employee, Payslip.employee_id == Employee.id)
        .filter(Payslip.month_year == month_year)
        .order_by(department, Employee.name)
        .all()
    )

    if not rows:
        return jsonify({"error": "No payslips found for the selected month."}), 404

    month_label = safe_filename(month_year)
    # Spool to disk so a full month of payslips is never held in memory twice
    archive = tempfile.TemporaryFile()
    written = 0
    used_names = set()
    try:
        # PDFs are already compressed, so store them as-is
        with PdfSources() as sources, zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
            for name, group in groupby(rows, key=lambda r: r[0]):
                pdf_bytes, _ = merge_payslip_pages([(b, n) for _, b, n in group], sources)
                if pdf_bytes is None:
                    continue
                base = safe_filename(name, "Unassigned")
                entry, suffix = base, 2
                while entry in used_names:
                    entry, suffix = f"{base}_{suffix}", suffix + 1
                used_names.add(entry)
                zf.writestr(f"{entry}_{month_label}.pdf", pdf_bytes)
                written += 1
    except Exception as e:
        archive.close()
        current_app.logger.exception("Department payslip ZIP export failed")
        return jsonify({"error": f"Failed to generate department PDFs: {str(e)}"}), 500

    if written == 0:
        archive.close()
        return jsonify({"error": NO_PAGES_ERROR}), 404

    archive.seek(0)
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"Department_Payslips_{month_label}.zip",
    )


@export_bp.route("/export/employee-bulk-payslips", methods=["GET"])
@jwt_required()
def export_employee_bulk_payslips_pdf():
    """Export a single merged PDF of payslips for a specific employee."""
    employee_id = request.args.get("employee_id", type=int)
    if not employee_id:
        return jsonify({"error": "employee_id is required"}), 400

    query = _payslip_pages_query().filter(Payslip.employee_id == employee_id)

    payslip_ids_str = request.args.get("payslip_ids", "")
    if payslip_ids_str:
        try:
            payslip_ids = [int(x) for x in payslip_ids_str.split(",") if x.strip()]
        except ValueError:
            return jsonify({"error": "payslip_ids must be a comma-separated list of numbers"}), 400
        if payslip_ids:
            query = query.filter(Payslip.id.in_(payslip_ids))

    pages = query.order_by(Payslip.month_year).all()

    if not pages:
        return jsonify({"error": "No payslips found for this employee."}), 404

    try:
        with PdfSources() as sources:
            pdf_bytes, _ = merge_payslip_pages(pages, sources)
    except Exception as e:
        current_app.logger.exception("Employee bulk payslip PDF export failed")
        return jsonify({"error": f"Failed to generate employee bulk PDF: {str(e)}"}), 500

    if pdf_bytes is None:
        return jsonify({"error": NO_PAGES_ERROR}), 404

    return _pdf_response(pdf_bytes, f"Employee_{employee_id}_Payslips.pdf", as_attachment=False)
