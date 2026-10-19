"""Excel parser service — reads the NOMINAL-PAYROLL Excel sheet and creates Employee records."""

import re

import openpyxl
from ..extensions import db
from ..models.employee import Employee
from ..models.employee_history import EmployeeHistory
from ..utils import normalize_gl

REQUIRED_FIELDS = ("ippis_number", "name")
OPTIONAL_FIELDS = ("file_no", "gl", "department", "division", "serial_no")

FIELD_LABELS = {
    "ippis_number": "IPPIS Number",
    "name": "Name",
    "file_no": "File No",
    "gl": "GL / Grade Level",
    "department": "Department",
    "division": "Division",
    "serial_no": "S/No",
}

# How far down the sheet to look for the header row (titles/logos often sit above it)
HEADER_SEARCH_ROWS = 30


def _tokens(header):
    """'Grade-Level (GL)' -> ('GRADE', 'LEVEL', 'GL')"""
    return tuple(re.sub(r"[^A-Z0-9]+", " ", str(header).upper()).split())


def match_column(header):
    """
    Map a header cell to an employee field, or None.

    Header wording drifts between nominal rolls ('IPPIS NO', 'IPPIS Number',
    'Dept', 'Department Name', 'Grade Level', 'GL'...), so each field is
    recognised by keywords rather than one exact title. Order matters: e.g.
    'Department Name' is a department, not a name.
    """
    words = _tokens(header)
    if not words:
        return None
    text = " ".join(words)

    if "IPPIS" in words or text in ("STAFF ID", "EMPLOYEE ID", "EMPLOYEE NUMBER"):
        return "ippis_number"
    if "FILE" in words or text in ("PF NO", "PERSONNEL NO", "PERSONNEL NUMBER"):
        return "file_no"
    if any(w in ("DEPT", "DEPTS", "DEPARTMENT", "DEPARTMENTS") for w in words):
        return "department"
    if any(w in ("DIV", "DIVISION", "DIVISIONS", "SECTION", "UNIT") for w in words):
        return "division"
    if "GL" in words or "GRADE" in words or text in ("LEVEL", "SALARY LEVEL"):
        return "gl"
    if "NAME" in words or "NAMES" in words:
        # Bank/PFA/next-of-kin names are not the employee's name
        if not any(w in ("BANK", "PFA", "ACCOUNT", "KIN", "MINISTRY") for w in words):
            return "name"
    if "SERIAL" in words or text in ("S NO", "S N", "SN", "SNO", "NO", "S"):
        return "serial_no"
    return None


def map_columns(header_row):
    """Return ({field: column index}, {field: header text}, [unrecognised headers])."""
    col_map, headers, unknown = {}, {}, []
    for i, cell in enumerate(header_row):
        if cell is None or not str(cell).strip():
            continue
        field = match_column(cell)
        if field and field not in col_map:
            col_map[field] = i
            headers[field] = str(cell).strip()
        elif not field:
            unknown.append(str(cell).strip())
    return col_map, headers, unknown


def _clean_digits(value):
    """'F/123' -> 123, 641215.0 -> 641215, '' -> None"""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    return int(digits) if digits else None


def read_nominal_roll(filepath):
    """
    Read the nominal roll into cleaned records without touching the database.

    Returns a dict with:
        header_row   - 1-based sheet row of the header (None if not found)
        col_map      - {field: column index}
        headers      - {field: header text as written in the sheet}
        unrecognised - header cells that matched no field
        records      - list of {ippis_number, name, file_no, gl, department, division, serial_no}
        skipped_rows - [(sheet row, reason)] for rows that could not be used
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    try:
        ws = wb.active
        result = {
            "header_row": None, "col_map": {}, "headers": {}, "unrecognised": [],
            "records": [], "skipped_rows": [],
        }
        col_map = None

        for row_num, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if col_map is None:
                # Look for the header row
                if row_num > HEADER_SEARCH_ROWS:
                    break
                candidate, headers, unknown = map_columns(row)
                if "ippis_number" in candidate:
                    col_map = candidate
                    result.update(header_row=row_num, col_map=candidate, headers=headers, unrecognised=unknown)
                continue

            # Skip completely empty rows
            if not any(cell is not None and str(cell).strip() for cell in row):
                continue

            def get_val(key):
                idx = col_map.get(key)
                if idx is not None and idx < len(row):
                    return row[idx]
                return None

            ippis_number = _clean_digits(get_val("ippis_number"))
            name = get_val("name")
            name = str(name).strip() if name is not None else ""

            # Skip rows without primary identifiers (totals, notes, blank lines)
            if not ippis_number:
                result["skipped_rows"].append((row_num, "no IPPIS number"))
                continue
            if not name:
                result["skipped_rows"].append((row_num, "no name"))
                continue

            department = get_val("department")
            division = get_val("division")
            serial_no = _clean_digits(get_val("serial_no"))
            result["records"].append({
                "ippis_number": ippis_number,
                "name": name,
                "file_no": _clean_digits(get_val("file_no")),
                "gl": normalize_gl(get_val("gl")),
                "department": str(department).strip() or None if department is not None else None,
                "division": str(division).strip() or None if division is not None else None,
                "serial_no": serial_no,
            })
        return result
    finally:
        wb.close()


def parse_excel(filepath, batch_id=None):
    """
    Parse the nominal payroll Excel file and create/update Employee records.
    Dynamically finds the header row to determine column indices.
    """
    sheet = read_nominal_roll(filepath)
    if sheet["header_row"] is None:
        raise ValueError("No header row with an IPPIS Number column was found in the Excel sheet.")
    col_map = sheet["col_map"]

    count = 0
    for record in sheet["records"]:
        gl_str = record["gl"]
        department_str = record["department"]
        division_str = record["division"]

        # Upsert
        employee = Employee.query.filter_by(ippis_number=record["ippis_number"]).first()
        if employee:
            # A sheet without a GL/department/division column says nothing about it:
            # keep what is on record instead of wiping it (GL is refilled from payslips)
            if "gl" not in col_map:
                gl_str = employee.gl
            if "department" not in col_map:
                department_str = employee.department
            if "division" not in col_map:
                division_str = employee.division

            if employee.gl != gl_str or employee.department != department_str or employee.division != division_str:
                db.session.add(EmployeeHistory(
                    employee_id=employee.id,
                    batch_id=batch_id,
                    old_gl=employee.gl,
                    old_department=employee.department,
                    old_division=employee.division,
                    new_gl=gl_str,
                    new_department=department_str,
                    new_division=division_str,
                ))

            employee.name = record["name"]
            if record["file_no"] is not None:
                employee.file_no = record["file_no"]
            employee.gl = gl_str
            employee.department = department_str
            employee.division = division_str
            if record["serial_no"] is not None:
                employee.serial_no = record["serial_no"]
        else:
            db.session.add(Employee(
                serial_no=record["serial_no"],
                file_no=record["file_no"] if record["file_no"] is not None else 0,  # Cannot be null
                ippis_number=record["ippis_number"],
                name=record["name"],
                gl=gl_str,
                department=department_str,
                division=division_str,
            ))

        count += 1
        if count % 200 == 0:
            db.session.commit()

    db.session.commit()
    return count
