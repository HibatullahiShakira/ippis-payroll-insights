"""Employee routes — search, filter, and detail views."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from ..extensions import db
from ..models.employee import Employee
from ..models.payslip import Payslip

employees_bp = Blueprint("employees", __name__)


@employees_bp.route("/employees", methods=["GET"])
@jwt_required()
def list_employees():
    """
    List and search employees with multi-field filtering.

    Query params:
        search   - General text search (name, file_no, ippis_number)
        name     - Filter by name (partial match)
        department - Filter by department (exact or partial)
        division - Filter by division (exact or partial)
        file_no  - Filter by file number (exact)
        ippis_number - Filter by IPPIS number (exact)
        gl       - Filter by grade level (exact)
        page     - Page number (default 1)
        per_page - Items per page (default 25, max 100)
        sort_by  - Sort field (name, file_no, ippis_number, department, gl)
        sort_order - asc or desc (default asc)
    """
    query = Employee.query

    # General search (searches across name, file_no, ippis_number)
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(
            or_(
                Employee.name.ilike(f"%{search}%"),
                Employee.file_no.cast(db.String).like(f"%{search}%"),
                Employee.ippis_number.cast(db.String).like(f"%{search}%"),
            )
        )

    # Specific field filters
    name = request.args.get("name", "").strip()
    if name:
        query = query.filter(Employee.name.ilike(f"%{name}%"))

    department = request.args.get("department", "").strip()
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    division = request.args.get("division", "").strip()
    if division:
        query = query.filter(Employee.division.ilike(f"%{division}%"))

    file_no = request.args.get("file_no", "").strip()
    if file_no:
        try:
            query = query.filter(Employee.file_no == int(file_no))
        except ValueError:
            pass

    ippis_number = request.args.get("ippis_number", "").strip()
    if ippis_number:
        try:
            query = query.filter(Employee.ippis_number == int(ippis_number))
        except ValueError:
            pass

    gl = request.args.get("gl", "").strip()
    if gl:
        query = query.filter(Employee.gl == gl)

    # Sorting
    sort_by = request.args.get("sort_by", "name")
    sort_order = request.args.get("sort_order", "asc")
    sort_column = getattr(Employee, sort_by, Employee.name)
    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 25, type=int), 100)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "employees": [e.to_summary_dict() for e in pagination.items],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        },
    })


@employees_bp.route("/employees/<int:employee_id>", methods=["GET"])
@jwt_required()
def get_employee(employee_id):
    """Get employee detail with payslip history."""
    employee = Employee.query.get_or_404(employee_id)

    # Get all payslips for this employee, ordered by month
    payslips = (
        Payslip.query
        .filter_by(employee_id=employee_id)
        .order_by(Payslip.month_year.desc())
        .all()
    )

    return jsonify({
        "employee": employee.to_dict(),
        "payslips": [p.to_summary_dict() for p in payslips],
    })


@employees_bp.route("/employees/departments", methods=["GET"])
@jwt_required()
def list_departments():
    """Get all unique department values for filter dropdowns."""
    departments = (
        db.session.query(Employee.department)
        .distinct()
        .filter(Employee.department.isnot(None))
        .order_by(Employee.department)
        .all()
    )
    return jsonify({"departments": [d[0] for d in departments]})


@employees_bp.route("/employees/divisions", methods=["GET"])
@jwt_required()
def list_divisions():
    """Get all unique division values for filter dropdowns."""
    department = request.args.get("department", "").strip()
    query = db.session.query(Employee.division).distinct().filter(Employee.division.isnot(None))

    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    divisions = query.order_by(Employee.division).all()
    return jsonify({"divisions": [d[0] for d in divisions]})


@employees_bp.route("/employees/gl-levels", methods=["GET"])
@jwt_required()
def list_gl_levels():
    """Get all unique GL values for filter dropdowns."""
    gls = (
        db.session.query(Employee.gl)
        .distinct()
        .filter(Employee.gl.isnot(None))
        .order_by(Employee.gl)
        .all()
    )
    return jsonify({"gl_levels": [g[0] for g in gls]})
