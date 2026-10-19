"""
One-off clean-up of employee GL data and Job History.

Two nominal-roll quirks were recorded in Job History as if they were real changes:

  * A roll without a GL or Division column blanked those fields for everyone
    (23 Aug 2026: GL and Division; 25 Sep 2026: GL). The import now treats a
    missing column as "keep what is on record"; this applies the same rule to the
    old entries: a field that went from a value to blank gets its value back, and
    an entry left with no real change is removed.
  * The August roll lays departments out differently (e.g. department SECURITY
    instead of department MD/CE + division SECURITY), so 23 Aug records a "move"
    and 25 Sep the "move back". These round trips are reported; they are only
    removed with --remove-round-trips, since a real transfer and return is possible.

It also fills each employee's blank GL from their most recent payslip and writes
every employee GL in the two-digit form ('8' -> '08').

By default it only REPORTS what it would do. Nothing changes without --apply.

    cd backend
    python -m scripts.clean_employee_history                     # report only
    python -m scripts.clean_employee_history --apply             # make the changes
    python -m scripts.clean_employee_history --apply --remove-round-trips

It uses DATABASE_URL from backend/.env, i.e. the database the app uses.
"""

import argparse
import sys
from collections import defaultdict

from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.models.employee import Employee
from app.models.employee_history import EmployeeHistory
from app.models.payslip import Payslip
from app.utils import normalize_gl

FIELDS = ("gl", "department", "division")


def db_host(app):
    url = app.config["SQLALCHEMY_DATABASE_URI"]
    return url.split("@")[-1] if "@" in url else url


def _norm(field, value):
    if value is None or not str(value).strip():
        return None
    return normalize_gl(value) if field == "gl" else str(value).strip().upper()


def plan():
    """Work out every change without making any."""
    entries = EmployeeHistory.query.order_by(
        EmployeeHistory.employee_id, EmployeeHistory.change_date, EmployeeHistory.id
    ).all()

    # Replay each employee's entries in order, tracking what is really known about
    # them. A blank in an entry means "column missing": the last known value stands.
    by_employee = defaultdict(list)
    for h in entries:
        by_employee[h.employee_id].append(h)

    removals, rewrites, real = [], [], defaultdict(list)
    for emp_entries in by_employee.values():
        known = {}
        for h in emp_entries:
            before, after = {}, {}
            for f in FIELDS:
                old, new = getattr(h, f"old_{f}"), getattr(h, f"new_{f}")
                before[f] = known.get(f) if known.get(f) is not None else (old if _norm(f, old) else None)
                after[f] = new if _norm(f, new) else before[f]
                if after[f] is not None:
                    known[f] = after[f]
            if all(_norm(f, before[f]) == _norm(f, after[f]) for f in FIELDS):
                removals.append(h)
                continue
            if any(getattr(h, f"old_{f}") != before[f] or getattr(h, f"new_{f}") != after[f] for f in FIELDS):
                rewrites.append((h, before, after))
            real[h.employee_id].append((h, before, after))

    # A department/division change exactly undone by the employee's next real change
    round_trips = []
    placement = ("department", "division")
    for items in real.values():
        i = 0
        while i + 1 < len(items):
            (a, a_before, a_after), (b, b_before, b_after) = items[i], items[i + 1]
            gl_unchanged = all(_norm("gl", x["gl"]) == _norm("gl", y["gl"])
                               for x, y in ((a_before, a_after), (b_before, b_after)))
            undone = gl_unchanged and all(
                _norm(f, b_after[f]) == _norm(f, a_before[f]) and _norm(f, b_before[f]) == _norm(f, a_after[f])
                for f in placement
            )
            if undone:
                round_trips.append((a, b))
                i += 2
            else:
                i += 1

    # Latest payslip grade per employee
    latest_month = (
        db.session.query(Payslip.employee_id, func.max(Payslip.month_year).label("month"))
        .group_by(Payslip.employee_id)
        .subquery()
    )
    latest_grade = dict(
        db.session.query(Payslip.employee_id, Payslip.grade)
        .join(latest_month, (Payslip.employee_id == latest_month.c.employee_id)
              & (Payslip.month_year == latest_month.c.month))
        .all()
    )
    gl_updates = []
    for emp in Employee.query.order_by(Employee.id):
        new_gl = normalize_gl(emp.gl) if emp.gl else normalize_gl(latest_grade.get(emp.id))
        if new_gl and new_gl != emp.gl:
            gl_updates.append((emp, new_gl))

    return {"entries": entries, "rewrites": rewrites, "removals": removals,
            "round_trips": round_trips, "gl_updates": gl_updates}


def main(argv=None, app=None):
    """app: the Flask app to use (tests pass theirs); by default the one configured by backend/.env."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="make the changes (default: report only)")
    parser.add_argument("--remove-round-trips", action="store_true",
                        help="also remove changes that the next entry exactly undoes")
    args = parser.parse_args(argv)

    app = app or create_app()
    print(f"Database: {db_host(app)}")
    with app.app_context():
        p = plan()
        removed_with_repair = p["removals"]
        repaired_ids = {h.id for h, _, _ in p["rewrites"]}
        round_trip_ids = {h.id for pair in p["round_trips"] for h in pair}
        filled = sum(1 for emp, _ in p["gl_updates"] if not emp.gl)

        print(f"Job History entries: {len(p['entries']):,}")
        print(f"  {len(removed_with_repair):,} record no real change once blanks are read as "
              "'column missing' -> remove")
        print(f"  {len(repaired_ids - round_trip_ids):,} record a real change but with blanked values "
              "-> keep, with the real before/after values")
        print(f"  {len(p['round_trips']):,} pairs where a change is exactly undone by the next entry "
              f"({len(round_trip_ids):,} entries) -> "
              + ("remove" if args.remove_round_trips else "kept (use --remove-round-trips to remove)"))
        for a, b in p["round_trips"][:3]:
            print(f"    e.g. employee {a.employee_id}: {a.old_department}/{a.old_division} -> "
                  f"{a.new_department}/{a.new_division or '-'} on {a.change_date:%d %b}, back on {b.change_date:%d %b}")
        remaining = len(p["entries"]) - len(removed_with_repair) - (len(round_trip_ids) if args.remove_round_trips else 0)
        print(f"  entries left afterwards: {remaining:,}")
        print(f"Employees: {Employee.query.count():,}")
        print(f"  {filled:,} with no GL -> fill from their latest payslip")
        print(f"  {len(p['gl_updates']) - filled:,} with GL in another format -> rewrite as two digits")

        if not args.apply:
            db.session.rollback()
            print("\nReport only - nothing was changed. Run again with --apply to make these changes.")
            return 0

        for h in p["removals"]:
            db.session.delete(h)
        for h, before, after in p["rewrites"]:
            for f in FIELDS:
                setattr(h, f"old_{f}", before[f])
                setattr(h, f"new_{f}", after[f])
        if args.remove_round_trips:
            for pair in p["round_trips"]:
                for h in pair:
                    db.session.delete(h)
        for emp, new_gl in p["gl_updates"]:
            emp.gl = new_gl
        db.session.commit()
        print("\nDone - changes saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
