"""Export routes — CSV download of filtered employee/payslip data."""

import io
import csv
from flask import Blueprint, request, Response
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
