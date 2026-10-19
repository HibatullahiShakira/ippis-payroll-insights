"""
Small, additive schema upgrades for an existing database.

The project has no migration history, so new columns/tables are added here when
the app first touches the database. Every step is safe to run repeatedly and
only ever adds things; nothing is dropped or rewritten except the one-off
backfill of the new payslip columns.
"""

import threading

from sqlalchemy import inspect, text

from .extensions import db

_lock = threading.Lock()
_done = False

# (table, column, SQL type) — all nullable
NEW_COLUMNS = [
    ("payslips", "department", "VARCHAR(200)"),
    ("payslips", "division", "VARCHAR(200)"),
    ("payslips", "gl", "VARCHAR(10)"),
]


def _backfill_payslip_snapshot(conn):
    """
    Give existing payslips the department/division the employee has on record now
    (the best information available for past months, and exactly what reports used
    until now), and the GL level from the grade printed on that month's payslip.
    """
    from .utils import normalize_gl

    conn.execute(text("""
        UPDATE payslips SET
            department = (SELECT e.department FROM employees e WHERE e.id = payslips.employee_id),
            division = (SELECT e.division FROM employees e WHERE e.id = payslips.employee_id)
        WHERE department IS NULL AND division IS NULL
    """))
    grades = conn.execute(text("SELECT DISTINCT grade FROM payslips WHERE gl IS NULL AND grade IS NOT NULL"))
    for (grade,) in grades.fetchall():
        conn.execute(
            text("UPDATE payslips SET gl = :gl WHERE grade = :grade AND gl IS NULL"),
            {"gl": normalize_gl(grade), "grade": grade},
        )


def ensure_schema():
    """Bring the database up to the current models. Runs once per process."""
    global _done
    if _done:
        return
    with _lock:
        if _done:
            return
        from .models import UploadReport

        engine = db.engine
        UploadReport.__table__.create(engine, checkfirst=True)

        inspector = inspect(engine)
        if not inspector.has_table("payslips"):
            # Fresh database: create_all() builds everything from the models
            _done = True
            return
        existing = {c["name"] for c in inspector.get_columns("payslips")}
        added = False
        with engine.begin() as conn:
            for table, column, sql_type in NEW_COLUMNS:
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
                    added = True
            if added:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_payslips_department ON payslips (department)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_payslips_gl ON payslips (gl)"))
                _backfill_payslip_snapshot(conn)
        _done = True


def reset_for_tests():
    global _done
    _done = False
