"""Utility helpers."""

import re
from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from sqlalchemy import func, or_

MONTH_YEAR_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Query value that selects employees with no department/division on record
UNASSIGNED = "__unassigned__"


def format_currency(amount):
    """Format a number as Nigerian Naira currency string."""
    if amount is None:
        return "₦0.00"
    return f"₦{float(amount):,.2f}"


def is_valid_month_year(value):
    """Check that a value looks like '2026-04'."""
    return bool(value) and bool(MONTH_YEAR_RE.match(value))


def current_user_from_jwt():
    """Return the User for the JWT on the current request, or None."""
    from ..extensions import db
    from ..models.user import User

    try:
        return db.session.get(User, int(get_jwt_identity()))
    except (TypeError, ValueError):
        return None


def admin_required(fn):
    """Route decorator — requires a valid JWT belonging to an active admin user."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user = current_user_from_jwt()
        if not user or not user.is_active or not user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)

    return wrapper


def _match_exact(column, value):
    """Case-insensitive exact match, with UNASSIGNED matching empty values."""
    if value == UNASSIGNED:
        return or_(column.is_(None), column == "")
    return func.lower(column) == value.lower()


def apply_employee_filters(query, args):
    """
    Apply the Employee Directory filters (search, department, division, gl) to a
    query that already includes Employee, so lists and exports always agree.
    """
    from ..extensions import db
    from ..models.employee import Employee

    search = args.get("search", "").strip()
    if search:
        query = query.filter(
            or_(
                Employee.name.ilike(f"%{search}%"),
                Employee.file_no.cast(db.String).like(f"%{search}%"),
                Employee.ippis_number.cast(db.String).like(f"%{search}%"),
            )
        )

    department = args.get("department", "").strip()
    if department:
        query = query.filter(_match_exact(Employee.department, department))

    division = args.get("division", "").strip()
    if division:
        query = query.filter(_match_exact(Employee.division, division))

    gl = args.get("gl", "").strip()
    if gl:
        gl_list = [g.strip() for g in gl.split(",") if g.strip()]
        if gl_list:
            query = query.filter(Employee.gl.in_(gl_list))

    return query
