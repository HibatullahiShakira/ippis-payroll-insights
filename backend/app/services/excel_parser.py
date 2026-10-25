"""Excel parser service — reads the NOMINAL-PAYROLL Excel sheet and creates Employee records."""

import re

import openpyxl
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


# IPPIS numbers in use are 6 digits; File Numbers are 5. A shorter "IPPIS" in a
# nominal roll is usually a File Number typed in the wrong column.
SHORT_IPPIS_LIMIT = 100000


def name_key(name):
    """'ABU, Mrs. JOAN ' -> 'ABUJOAN': for matching the same person across sources."""
    text = re.sub(r"\b(MR|MRS|MS|MISS|DR|ENGR|ALH|CHIEF)\b\.?", " ", str(name or "").upper())
    return re.sub(r"[^A-Z]", "", text)


def remap_file_number_rows(records, employees):
    """
    Fix rows whose IPPIS column holds the employee's File Number.

    A row whose "IPPIS" is not on record, but equals the File No of an employee
    with the same name, is that employee: the row is re-keyed to their real IPPIS
    number (and the value kept as their File No) instead of creating a duplicate.

    employees: iterable of dicts with ippis_number, file_no and name.
    Returns (records, remapped) where remapped lists (row value, real IPPIS, name).
    """
    employees = list(employees)
    on_record = {e["ippis_number"] for e in employees}
    by_file = {(e["file_no"], name_key(e["name"])): e for e in employees if e.get("file_no")}
    out, remapped = [], []
    for rec in records:
        match = None
        if rec["ippis_number"] not in on_record:
            match = by_file.get((rec["ippis_number"], name_key(rec["name"])))
        if match:
            remapped.append((rec["ippis_number"], match["ippis_number"], rec["name"]))
            rec = {**rec, "ippis_number": match["ippis_number"], "file_no": rec["ippis_number"]}
        out.append(rec)
    return out, remapped


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


def parse_excel(filepath, batch_id=None, progress_offset=0):
    """
    Parse the nominal payroll Excel file and create/update Employee records.
    Dynamically finds the header row to determine column indices.

    Rows are saved in batches with progress recorded on the upload batch.
    Returns the number of employees saved.
    """
    from .import_writer import Progress, save_employees

    sheet = read_nominal_roll(filepath)
    if sheet["header_row"] is None:
        raise ValueError("No header row with an IPPIS Number column was found in the Excel sheet.")

    count, failed, first_error = save_employees(
        sheet["records"], sheet["col_map"], batch_id=batch_id,
        progress=Progress(batch_id, progress_offset) if batch_id else None,
    )
    if failed:
        print(f"{failed} nominal-roll row(s) could not be saved; first error: {first_error}")
    return count
