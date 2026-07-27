"""Analytics routes — department summaries, GL distribution, deduction breakdown, trends."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from ..extensions import db
from ..models.employee import Employee
from ..models.payslip import Payslip
from ..models.payslip_deduction import PayslipDeduction
from ..models.payslip_earning import PayslipEarning

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/department-summary", methods=["GET"])
@jwt_required()
def department_summary():
    """
    Get salary summary per department for a given month.
    Query params: month_year (optional — defaults to latest)
    """
    month_year = request.args.get("month_year")

    # If no month specified, use the latest
    if not month_year:
        latest = db.session.query(Payslip.month_year).order_by(Payslip.month_year.desc()).first()
        if not latest:
            return jsonify({"departments": [], "month_year": None})
        month_year = latest[0]

    results = (
        db.session.query(
            Employee.department,
            func.count(Payslip.id).label("headcount"),
            func.sum(Payslip.total_gross_earnings).label("total_earnings"),
            func.sum(Payslip.total_gross_deductions).label("total_deductions"),
            func.sum(Payslip.total_net_earnings).label("total_net"),
            func.avg(Payslip.total_net_earnings).label("avg_net"),
        )
        .join(Employee, Payslip.employee_id == Employee.id)
        .filter(Payslip.month_year == month_year)
        .group_by(Employee.department)
        .order_by(func.sum(Payslip.total_gross_earnings).desc())
        .all()
    )

    departments = []
    for row in results:
        departments.append({
            "department": row.department or "Unknown",
            "headcount": row.headcount,
            "total_earnings": float(row.total_earnings or 0),
            "total_deductions": float(row.total_deductions or 0),
            "total_net": float(row.total_net or 0),
            "avg_net": round(float(row.avg_net or 0), 2),
        })

    return jsonify({"departments": departments, "month_year": month_year})


@analytics_bp.route("/gl-distribution", methods=["GET"])
@jwt_required()
def gl_distribution():
    """
    Get employee count and salary totals per GL level.
    Query params: month_year (optional)
    """
    month_year = request.args.get("month_year")

    if not month_year:
        latest = db.session.query(Payslip.month_year).order_by(Payslip.month_year.desc()).first()
        if not latest:
            return jsonify({"gl_levels": [], "month_year": None})
        month_year = latest[0]

    results = (
        db.session.query(
            Employee.gl,
            func.count(Payslip.id).label("headcount"),
            func.sum(Payslip.total_gross_earnings).label("total_earnings"),
            func.avg(Payslip.total_gross_earnings).label("avg_earnings"),
        )
        .join(Employee, Payslip.employee_id == Employee.id)
        .filter(Payslip.month_year == month_year)
        .group_by(Employee.gl)
        .order_by(Employee.gl)
        .all()
    )

    gl_levels = []
    for row in results:
        gl_levels.append({
            "gl": row.gl or "N/A",
            "headcount": row.headcount,
            "total_earnings": float(row.total_earnings or 0),
            "avg_earnings": round(float(row.avg_earnings or 0), 2),
        })

    return jsonify({"gl_levels": gl_levels, "month_year": month_year})


@analytics_bp.route("/deduction-breakdown", methods=["GET"])
@jwt_required()
def deduction_breakdown():
    """
    Get deduction categories with totals and employee count.
    Query params: month_year (optional)
    """
    month_year = request.args.get("month_year")

    if not month_year:
        latest = db.session.query(Payslip.month_year).order_by(Payslip.month_year.desc()).first()
        if not latest:
            return jsonify({"deductions": [], "month_year": None})
        month_year = latest[0]

    results = (
        db.session.query(
            PayslipDeduction.deduction_type,
            func.count(PayslipDeduction.id).label("count"),
            func.sum(PayslipDeduction.amount).label("total_amount"),
            func.avg(PayslipDeduction.amount).label("avg_amount"),
        )
        .join(Payslip, PayslipDeduction.payslip_id == Payslip.id)
        .filter(Payslip.month_year == month_year)
        .group_by(PayslipDeduction.deduction_type)
        .order_by(func.sum(PayslipDeduction.amount).desc())
        .all()
    )

    deductions = []
    for row in results:
        deductions.append({
            "deduction_type": row.deduction_type,
            "count": row.count,
            "total_amount": float(row.total_amount or 0),
            "avg_amount": round(float(row.avg_amount or 0), 2),
        })

    return jsonify({"deductions": deductions, "month_year": month_year})


@analytics_bp.route("/salary-trends/<int:employee_id>", methods=["GET"])
@jwt_required()
def salary_trends(employee_id):
    """Get month-over-month earnings, deductions, and net pay for an employee."""
    employee = Employee.query.get_or_404(employee_id)

    payslips = (
        Payslip.query
        .filter_by(employee_id=employee_id)
        .order_by(Payslip.month_year.asc())
        .all()
    )

    trends = []
    for p in payslips:
        trends.append({
            "month_year": p.month_year,
            "gross_earnings": float(p.total_gross_earnings or 0),
            "gross_deductions": float(p.total_gross_deductions or 0),
            "net_earnings": float(p.total_net_earnings or 0),
        })

    return jsonify({
        "employee": employee.to_summary_dict(),
        "trends": trends,
    })


@analytics_bp.route("/monthly-overview", methods=["GET"])
@jwt_required()
def monthly_overview():
    """Get total payroll expenditure per uploaded month."""
    results = (
        db.session.query(
            Payslip.month_year,
            func.count(Payslip.id).label("employee_count"),
            func.sum(Payslip.total_gross_earnings).label("total_earnings"),
            func.sum(Payslip.total_gross_deductions).label("total_deductions"),
            func.sum(Payslip.total_net_earnings).label("total_net"),
        )
        .group_by(Payslip.month_year)
        .order_by(Payslip.month_year.desc())
        .all()
    )

    months = []
    for row in results:
        months.append({
            "month_year": row.month_year,
            "employee_count": row.employee_count,
            "total_earnings": float(row.total_earnings or 0),
            "total_deductions": float(row.total_deductions or 0),
            "total_net": float(row.total_net or 0),
        })

    return jsonify({"months": months})
