import re

with open("backend/app/services/pdf_parser.py", "r") as f:
    content = f.read()

target = """                if not employee_id:
                    # Create a minimal employee record if not found in Excel
                    employee = Employee(
                        ippis_number=ippis,
                        name=payslip_data.get("name", "Unknown"),
                        file_no=0,
                        gl=None,
                    )
                    db.session.add(employee)
                    db.session.flush()
                    employee_id = employee.id
                    employee_id_by_ippis[ippis] = employee_id"""

replacement = """                # Extract numeric grade level from payslip (e.g. "GL13_CONPSS" -> "13")
                raw_grade = payslip_data.get("grade")
                extracted_gl = None
                if raw_grade:
                    m = re.search(r'\d+', raw_grade)
                    if m:
                        extracted_gl = m.group(0).zfill(2)
                    else:
                        extracted_gl = raw_grade[:10]

                if not employee_id:
                    # Create a minimal employee record if not found in Excel
                    employee = Employee(
                        ippis_number=ippis,
                        name=payslip_data.get("name", "Unknown"),
                        file_no=0,
                        gl=extracted_gl,
                    )
                    db.session.add(employee)
                    db.session.flush()
                    employee_id = employee.id
                    employee_id_by_ippis[ippis] = employee_id
                else:
                    # Update existing employee's GL from the latest payslip
                    if extracted_gl:
                        emp_obj = db.session.query(Employee).get(employee_id)
                        if emp_obj:
                            emp_obj.gl = extracted_gl"""

new_content = content.replace(target, replacement)
if new_content == content:
    print("REPLACEMENT FAILED")
else:
    with open("backend/app/services/pdf_parser.py", "w", encoding='utf-8') as f:
        f.write(new_content)
    print("SUCCESS")
