"""Excel parser service — reads the NOMINAL-PAYROLL Excel sheet and creates Employee records."""

import openpyxl
from ..extensions import db
from ..models.employee import Employee
from ..models.employee_history import EmployeeHistory


def parse_excel(filepath, batch_id=None):
    """
    Parse the nominal payroll Excel file and create/update Employee records.

    Expected columns (row 2 is header):
        A: S/NO
        B: FILE NO
        C: IPPIS NUMBER
        D: NAME
        E: GL
        F: DEPT
        G: DIVISION

    Returns:
        int: Number of employees processed.
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    count = 0
    # Data starts at row 3 (row 1 = company name, row 2 = headers)
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row):
        # Extract cell values safely
        serial_no = row[0].value if len(row) > 0 else None
        file_no = row[1].value if len(row) > 1 else None
        ippis_number = row[2].value if len(row) > 2 else None
        name = row[3].value if len(row) > 3 else None
        gl = row[4].value if len(row) > 4 else None
        department = row[5].value if len(row) > 5 else None
        division = row[6].value if len(row) > 6 else None

        # Skip empty rows
        if not ippis_number or not name:
            continue

        # Convert types
        try:
            file_no = int(file_no) if file_no else None
            ippis_number = int(ippis_number)
        except (ValueError, TypeError):
            continue

        gl_str = str(gl).strip() if gl else None
        department_str = str(department).strip() if department else None
        division_str = str(division).strip() if division else None

        # Upsert: update existing or create new
        employee = Employee.query.filter_by(ippis_number=ippis_number).first()

        if employee:
            # Check if relevant fields changed
            changed = False
            if employee.gl != gl_str or employee.department != department_str or employee.division != division_str:
                changed = True
                
                # Record history
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

            # Update existing record
            employee.name = str(name).strip()
            employee.file_no = file_no
            employee.gl = gl_str
            employee.department = department_str
            employee.division = division_str
            if serial_no:
                employee.serial_no = int(serial_no)
        else:
            # Create new employee
            employee = Employee(
                serial_no=int(serial_no) if serial_no else None,
                file_no=file_no,
                ippis_number=ippis_number,
                name=str(name).strip(),
                gl=gl_str,
                department=str(department).strip() if department else None,
                division=str(division).strip() if division else None,
            )
            db.session.add(employee)

        count += 1

        # Batch commit every 200 records
        if count % 200 == 0:
            db.session.commit()

    db.session.commit()
    wb.close()

    return count
