"""Excel parser service — reads the NOMINAL-PAYROLL Excel sheet and creates Employee records."""

import openpyxl
from ..extensions import db
from ..models.employee import Employee
from ..models.employee_history import EmployeeHistory


def parse_excel(filepath, batch_id=None):
    """
    Parse the nominal payroll Excel file and create/update Employee records.
    Dynamically finds the header row to determine column indices.
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    count = 0
    col_map = {}
    header_found = False

    for row in ws.iter_rows(values_only=True):
        # Convert row values to strings for easy checking
        str_row = [str(cell).upper().strip() if cell is not None else "" for cell in row]
        
        # Look for the header row
        if not header_found:
            if "IPPIS NUMBER" in str_row or any("IPPIS" in c for c in str_row):
                header_found = True
                for i, col_name in enumerate(str_row):
                    if "S/NO" in col_name or "SERIAL" in col_name:
                        col_map["serial_no"] = i
                    elif "FILE NO" in col_name or "FILE" in col_name:
                        col_map["file_no"] = i
                    elif "IPPIS" in col_name:
                        col_map["ippis_number"] = i
                    elif "NAME" in col_name:
                        col_map["name"] = i
                    elif "GL" in col_name or "GRADE" in col_name:
                        col_map["gl"] = i
                    elif "DEPT" in col_name or "DEPARTMENT" in col_name:
                        col_map["department"] = i
                    elif "DIV" in col_name:
                        col_map["division"] = i
            continue

        # Data rows
        if header_found:
            # Skip completely empty rows
            if not any(row):
                continue
            
            # Safely get value by mapped column
            def get_val(key):
                idx = col_map.get(key)
                if idx is not None and idx < len(row):
                    return row[idx]
                return None

            serial_no = get_val("serial_no")
            file_no = get_val("file_no")
            ippis_number = get_val("ippis_number")
            name = get_val("name")
            gl = get_val("gl")
            department = get_val("department")
            division = get_val("division")

            # Skip rows without primary identifiers
            if not ippis_number or not name:
                continue

            # Convert types safely
            try:
                # file_no could be a string like "F123"
                if file_no:
                    file_no_str = str(file_no).strip()
                    file_no_digits = ''.join(filter(str.isdigit, file_no_str))
                    file_no = int(file_no_digits) if file_no_digits else None
                else:
                    file_no = None

                ippis_str = str(ippis_number).strip()
                ippis_digits = ''.join(filter(str.isdigit, ippis_str))
                if not ippis_digits:
                    continue
                ippis_number = int(ippis_digits)
            except (ValueError, TypeError):
                continue

            gl_str = str(gl).strip() if gl is not None else None
            department_str = str(department).strip() if department is not None else None
            division_str = str(division).strip() if division is not None else None

            # Upsert
            employee = Employee.query.filter_by(ippis_number=ippis_number).first()
            if employee:
                changed = False
                if employee.gl != gl_str or employee.department != department_str or employee.division != division_str:
                    changed = True
                    history = EmployeeHistory(
                        employee_id=employee.id,
                        batch_id=batch_id,
                        old_gl=employee.gl,
                        old_department=employee.department,
                        old_division=employee.division,
                        new_gl=gl_str,
                        new_department=department_str,
                        new_division=division_str
                    )
                    db.session.add(history)

                employee.name = str(name).strip()
                employee.file_no = file_no if file_no is not None else employee.file_no
                employee.gl = gl_str
                employee.department = department_str
                employee.division = division_str
                if serial_no:
                    try:
                        employee.serial_no = int(serial_no)
                    except (ValueError, TypeError):
                        pass
            else:
                employee = Employee(
                    serial_no=int(serial_no) if serial_no and str(serial_no).isdigit() else None,
                    file_no=file_no if file_no is not None else 0, # Cannot be null
                    ippis_number=ippis_number,
                    name=str(name).strip(),
                    gl=gl_str,
                    department=department_str,
                    division=division_str,
                )
                db.session.add(employee)

            count += 1

            if count % 200 == 0:
                db.session.commit()

    db.session.commit()
    wb.close()

    return count
