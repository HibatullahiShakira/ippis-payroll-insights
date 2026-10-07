"""Payslip routes — list and detail views."""

from flask import Blueprint, request, jsonify, send_file, current_app
from flask_jwt_extended import jwt_required
import io

from ..models.payslip import Payslip
from ..models.employee import Employee
from ..services.pdf_export import PdfSources, merge_payslip_pages, safe_filename

payslips_bp = Blueprint("payslips", __name__)


@payslips_bp.route("/payslips", methods=["GET"])
@jwt_required()
def list_payslips():
    """
    List payslips with filters.

    Query params:
        employee_id  - Filter by employee
        month_year   - Filter by month (e.g., '2026-04')
        department   - Filter by employee's department
        gl           - Filter by employee's GL
        page, per_page - Pagination
    """
    query = Payslip.query.join(Employee)

    employee_id = request.args.get("employee_id", type=int)
    if employee_id:
        query = query.filter(Payslip.employee_id == employee_id)

    month_year = request.args.get("month_year", "").strip()
    if month_year:
        query = query.filter(Payslip.month_year == month_year)

    department = request.args.get("department", "").strip()
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    gl = request.args.get("gl", "").strip()
    if gl:
        gl_list = [g.strip() for g in gl.split(",") if g.strip()]
        if gl_list:
            query = query.filter(Employee.gl.in_(gl_list))

    # Sorting
    query = query.order_by(Payslip.month_year.desc(), Employee.name.asc())

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 25, type=int), 100)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    results = []
    for payslip in pagination.items:
        data = payslip.to_summary_dict()
        data["employee_name"] = payslip.employee.name
        data["department"] = payslip.employee.department
        data["ippis_number"] = payslip.employee.ippis_number
        results.append(data)

    return jsonify({
        "payslips": results,
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        },
    })


@payslips_bp.route("/payslips/<int:payslip_id>", methods=["GET"])
@jwt_required()
def get_payslip(payslip_id):
    """Get full payslip detail including earnings and deductions breakdown."""
    payslip = Payslip.query.get_or_404(payslip_id)
    employee = Employee.query.get(payslip.employee_id)

    result = payslip.to_dict()
    result["employee"] = employee.to_dict() if employee else None

    return jsonify({"payslip": result})


@payslips_bp.route("/payslips/<int:payslip_id>/pdf", methods=["GET"])
@jwt_required()
def get_payslip_pdf(payslip_id):
    """Download the single page PDF for a payslip."""
    payslip = Payslip.query.get_or_404(payslip_id)
    employee = Employee.query.get(payslip.employee_id)
    
    if payslip.pdf_page_num is None:
        return jsonify({"error": "No PDF page associated with this payslip."}), 404

    try:
        with PdfSources() as sources:
            if not sources.path_for(payslip.batch_id):
                return jsonify({"error": "Original PDF file not found. Re-upload the bulk PDF for this month."}), 404
            pdf_bytes, _ = merge_payslip_pages([(payslip.batch_id, payslip.pdf_page_num)], sources)
    except Exception as e:
        current_app.logger.exception("Payslip PDF export failed")
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500

    if pdf_bytes is None:
        return jsonify({"error": "This payslip's page is missing from the original PDF."}), 404

    name = safe_filename(employee.name if employee else "", "Employee")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"Payslip_{name}_{payslip.month_year}.pdf",
    )


@payslips_bp.route("/payslips/months", methods=["GET"])
@jwt_required()
def list_months():
    """Get all available months with payslip data."""
    from ..extensions import db

    months = (
        db.session.query(Payslip.month_year)
        .distinct()
        .order_by(Payslip.month_year.desc())
        .all()
    )
    return jsonify({"months": [m[0] for m in months]})
