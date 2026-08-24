"""
PDF parser service â€” extracts full payslip data from the bulk payslip PDF.

Each page in the PDF is one employee's payslip with this structure:
    - Employee Name, Grade
    - IPPIS Number, Step
    - Ministry, Gender
    - Designation, Tax State
    - Location, TIN
    - Date of First Appointment
    - Date of Birth
    - Trade Union
    - Bank Information (Bank Name, Account Number)
    - Pension Information (PFA Name, Pension PIN)
    - Summary of Payments (Gross Earnings, Gross Deductions, Net Earnings)
    - Cumulative Balances (Tax, Income, Pension, NHF)
    - Earnings breakdown table (type â†’ amount)
    - Deductions breakdown table (type â†’ amount)
"""

import re
from decimal import Decimal, InvalidOperation

from ..extensions import db
from ..models.employee import Employee
from ..models.payslip import Payslip
from ..models.payslip_earning import PayslipEarning
from ..models.payslip_deduction import PayslipDeduction
from ..models.upload_batch import UploadBatch


def parse_pdf(filepath, batch_id, month_year):
    """
    Parse the bulk payslip PDF file and create Payslip records.

    Args:
        filepath: Path to the PDF file.
        batch_id: The UploadBatch ID to associate payslips with.
        month_year: The month string (e.g., '2026-04').

    Returns:
        int: Number of payslips successfully parsed.
    """
    count = 0

    import fitz  # PyMuPDF

    with fitz.open(filepath) as doc:
        total_pages = doc.page_count
        
        batch = UploadBatch.query.get(batch_id)
        if batch:
            batch.total_records = total_pages

        # Peek at the first page to extract the actual month/year from the PDF text
        try:
            if total_pages > 0:
                first_page_text = doc.load_page(0).get_text("text")
                first_page_data = _parse_page_text(first_page_text)
                if first_page_data and first_page_data.get("extracted_month_year"):
                    month_year = first_page_data["extracted_month_year"]
        except Exception as e:
            print(f"Could not extract month/year from first page: {e}")

        # PERFORMANCE OPTIMIZATION: Pre-load DB records into memory dictionaries. 
        # By loading ONLY the IDs and not the full SQLAlchemy objects, we save hundreds of MB of RAM!
        employees_data = db.session.query(Employee.ippis_number, Employee.id).all()
        employee_id_by_ippis = {ippis: emp_id for ippis, emp_id in employees_data}
        
        payslips_data = db.session.query(Payslip.employee_id, Payslip.id).filter_by(month_year=month_year).all()
        payslip_id_by_emp_id = {emp_id: p_id for emp_id, p_id in payslips_data}

        for page_num in range(total_pages):
            try:
                # Create a savepoint for this specific page
                nested = db.session.begin_nested()
                page = doc.load_page(page_num)
                # get_text("text") mimics pdfplumber's reading order output almost perfectly
                text = page.get_text("text")
                page = None # Free page object from memory early
                
                if not text:
                    nested.rollback()
                    continue

                payslip_data = _parse_page_text(text)
                if not payslip_data or not payslip_data.get("ippis_number"):
                    nested.rollback()
                    continue

                payslip_data["pdf_page_num"] = page_num

                # Find the employee by IPPIS number in memory
                ippis = payslip_data["ippis_number"]
                employee_id = employee_id_by_ippis.get(ippis)

                # Get the grade and use the full grade string
                grade_str = payslip_data.get("grade")
                extracted_gl = grade_str if grade_str else None

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
                            emp_obj.gl = extracted_gl

                # Check for existing payslip in memory
                existing_payslip_id = payslip_id_by_emp_id.get(employee_id)
                if existing_payslip_id:
                    # Clear out old earnings and deductions so we can insert new ones
                    db.session.query(PayslipEarning).filter_by(payslip_id=existing_payslip_id).delete(synchronize_session=False)
                    db.session.query(PayslipDeduction).filter_by(payslip_id=existing_payslip_id).delete(synchronize_session=False)
                    
                    # Update existing payslip with new data
                    payslip = db.session.query(Payslip).get(existing_payslip_id)
                    payslip.batch_id = batch_id
                    payslip.grade = payslip_data.get("grade")
                    payslip.step = payslip_data.get("step")
                    payslip.gender = payslip_data.get("gender")
                    payslip.tax_state = payslip_data.get("tax_state")
                    payslip.designation = payslip_data.get("designation")
                    payslip.date_of_birth = payslip_data.get("date_of_birth")
                    payslip.date_of_first_appt = payslip_data.get("date_of_first_appt")
                    payslip.trade_union = payslip_data.get("trade_union")
                    payslip.bank_name = payslip_data.get("bank_name")
                    payslip.account_number = payslip_data.get("account_number")
                    payslip.pfa_name = payslip_data.get("pfa_name")
                    payslip.pension_pin = payslip_data.get("pension_pin")
                    payslip.total_gross_earnings = payslip_data.get("total_gross_earnings")
                    payslip.total_gross_deductions = payslip_data.get("total_gross_deductions")
                    payslip.total_net_earnings = payslip_data.get("total_net_earnings")
                    payslip.cumulative_tax = payslip_data.get("cumulative_tax")
                    payslip.cumulative_income = payslip_data.get("cumulative_income")
                    payslip.cumulative_pension = payslip_data.get("cumulative_pension")
                    payslip.cumulative_nhf = payslip_data.get("cumulative_nhf")
                    payslip.pdf_page_num = page_num
                    target_payslip = payslip
                else:
                    # Create new payslip
                    payslip = Payslip(
                        employee_id=employee_id,
                        batch_id=batch_id,
                        month_year=month_year,
                        grade=payslip_data.get("grade"),
                        step=payslip_data.get("step"),
                        gender=payslip_data.get("gender"),
                        tax_state=payslip_data.get("tax_state"),
                        designation=payslip_data.get("designation"),
                        date_of_birth=payslip_data.get("date_of_birth"),
                        date_of_first_appt=payslip_data.get("date_of_first_appt"),
                        trade_union=payslip_data.get("trade_union"),
                        bank_name=payslip_data.get("bank_name"),
                        account_number=payslip_data.get("account_number"),
                        pfa_name=payslip_data.get("pfa_name"),
                        pension_pin=payslip_data.get("pension_pin"),
                        total_gross_earnings=payslip_data.get("total_gross_earnings"),
                        total_gross_deductions=payslip_data.get("total_gross_deductions"),
                        total_net_earnings=payslip_data.get("total_net_earnings"),
                        cumulative_tax=payslip_data.get("cumulative_tax"),
                        cumulative_income=payslip_data.get("cumulative_income"),
                        cumulative_pension=payslip_data.get("cumulative_pension"),
                        cumulative_nhf=payslip_data.get("cumulative_nhf"),
                        pdf_page_num=page_num,
                    )
                    db.session.add(payslip)
                    db.session.flush()
                    payslip_id_by_emp_id[employee_id] = payslip.id
                    target_payslip = payslip

                # Add earnings
                for earning in payslip_data.get("earnings", []):
                    db.session.add(PayslipEarning(
                        payslip_id=target_payslip.id,
                        earning_type=earning["type"],
                        amount=earning["amount"],
                    ))

                # Add deductions
                for deduction in payslip_data.get("deductions", []):
                    db.session.add(PayslipDeduction(
                        payslip_id=target_payslip.id,
                        deduction_type=deduction["type"],
                        amount=deduction["amount"],
                    ))

                count += 1
                nested.commit()  # Release savepoint on success

                # Batch commit and update progress
                if count % 50 == 0:
                    if batch:
                        batch.records_processed = count
                    db.session.commit()

            except Exception as e:
                nested.rollback()  # Rollback only this page on error
                # Log error but continue processing other pages
                print(f"Error parsing page {page_num + 1}: {e}")
                continue
            finally:
                # Force garbage collection every 50 pages to ensure PyPDF2 and pdfplumber objects are freed
                if count > 0 and count % 50 == 0:
                    import gc
                    gc.collect()

    # Final commit
    if batch:
        batch.records_processed = count
    db.session.commit()

    return count


def _update_payslip(payslip, data):
    """Update an existing payslip with new data."""
    for field in [
        "grade", "step", "gender", "tax_state", "designation",
        "date_of_birth", "date_of_first_appt", "trade_union",
        "bank_name", "account_number", "pfa_name", "pension_pin",
        "total_gross_earnings", "total_gross_deductions", "total_net_earnings",
        "cumulative_tax", "cumulative_income", "cumulative_pension", "cumulative_nhf",
        "pdf_page_num",
    ]:
        if data.get(field) is not None:
            setattr(payslip, field, data[field])


def _parse_page_text(text):
    """
    Parse a single payslip page's text into structured data.

    The text follows the IPPIS SoftSUITE payslip format.
    """
    data = {
        "earnings": [],
        "deductions": [],
    }

    lines = text.split("\n")
    full_text = text

    # --- Extract Month and Year ---
    month_match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)[\s,]+(\d{4})", full_text, re.IGNORECASE)
    if month_match:
        month_str = month_match.group(1).capitalize()
        year_str = month_match.group(2)
        month_map = {
            "January": "01", "February": "02", "March": "03", "April": "04",
            "May": "05", "June": "06", "July": "07", "August": "08",
            "September": "09", "October": "10", "November": "11", "December": "12"
        }
        data["extracted_month_year"] = f"{year_str}-{month_map[month_str]}"

    # --- Extract IPPIS Number ---
    ippis_match = re.search(r"IPPIS\s*Number[:\s]*(\d+)", full_text, re.IGNORECASE)
    if ippis_match:
        try:
            data["ippis_number"] = int(ippis_match.group(1))
        except ValueError:
            return None
    else:
        return None

    # --- Extract Employee Name ---
    name_match = re.search(
        r"Employee\s*Name\s*([A-Z][A-Z\s,.\-']+?)(?:\s*Grade|\s*$)",
        full_text,
        re.IGNORECASE,
    )
    if name_match:
        name = name_match.group(1).strip()
        # Clean up title prefixes that got captured
        name = re.sub(r"\b(Mr\.|Mrs\.|Ms\.|Dr\.)\s*", "", name).strip()
        data["name"] = name

    # --- Extract Grade ---
    grade_match = re.search(r"Grade[:\s]*([A-Z0-9_]+)", full_text, re.IGNORECASE)
    if grade_match:
        data["grade"] = grade_match.group(1).strip()

    # --- Extract Step ---
    step_match = re.search(r"Step[:\s]*(\d+)", full_text, re.IGNORECASE)
    if step_match:
        try:
            data["step"] = int(step_match.group(1))
        except ValueError:
            pass

    # --- Extract Gender ---
    gender_match = re.search(r"Gender[:\s]*(MALE|FEMALE)", full_text, re.IGNORECASE)
    if gender_match:
        data["gender"] = gender_match.group(1).upper()

    # --- Extract Tax State ---
    tax_match = re.search(r"Tax\s*State[:\s]*([A-Z]+)", full_text, re.IGNORECASE)
    if tax_match:
        data["tax_state"] = tax_match.group(1).strip()

    # --- Extract Designation ---
    desig_match = re.search(
        r"Designation[:\s]*(.+?)(?:\s*Tax\s*State|\s*$)",
        full_text,
        re.IGNORECASE,
    )
    if desig_match:
        data["designation"] = desig_match.group(1).strip()

    # --- Extract Date of Birth ---
    dob_match = re.search(
        r"Date\s*of\s*Birth\s*[:\s]*(\d{1,2}[-/][A-Z]{3}[-/]\d{4})",
        full_text,
        re.IGNORECASE,
    )
    if dob_match:
        data["date_of_birth"] = dob_match.group(1)

    # --- Extract Date of First Appointment ---
    appt_match = re.search(
        r"Date\s*of\s*First\s*Appt[:\s]*(\d{1,2}[-/][A-Z]{3}[-/]\d{4})",
        full_text,
        re.IGNORECASE,
    )
    if appt_match:
        data["date_of_first_appt"] = appt_match.group(1)

    # --- Extract Trade Union ---
    union_match = re.search(r"Trade\s*Union[:\s]*(.+?)(?:\n|Bank)", full_text, re.IGNORECASE)
    if union_match:
        data["trade_union"] = union_match.group(1).strip()

    # --- Extract Bank Name ---
    bank_match = re.search(r"Bank\s*Name[:\s]*(.+?)(?:\n|PFA|Account)", full_text, re.IGNORECASE)
    if bank_match:
        bank = bank_match.group(1).strip()
        # Clean up trailing text
        bank = re.sub(r"\s*(PFA|Pension|Account).*", "", bank, flags=re.IGNORECASE).strip()
        data["bank_name"] = bank

    # --- Extract Account Number ---
    acct_match = re.search(r"Account\s*Number[:\s]*(\d+)", full_text, re.IGNORECASE)
    if acct_match:
        data["account_number"] = acct_match.group(1)

    # --- Extract PFA Name ---
    pfa_match = re.search(r"PFA\s*Name[:\s]*(.+?)(?:\n|Pension\s*PIN|Account)", full_text, re.IGNORECASE)
    if pfa_match:
        pfa = pfa_match.group(1).strip()
        pfa = re.sub(r"\s*(Pension|Account).*", "", pfa, flags=re.IGNORECASE).strip()
        data["pfa_name"] = pfa

    # --- Extract Pension PIN ---
    pin_match = re.search(r"Pension\s*PIN[:\s]*(\d+)", full_text, re.IGNORECASE)
    if pin_match:
        data["pension_pin"] = pin_match.group(1)

    # --- Extract Summary Totals ---
    gross_earn_match = re.search(
        r"Total\s*Gross\s*Earnings?\s*[:\s]*([\d,]+\.?\d*)",
        full_text,
        re.IGNORECASE,
    )
    if gross_earn_match:
        data["total_gross_earnings"] = _parse_amount(gross_earn_match.group(1))

    gross_ded_match = re.search(
        r"Total\s*Gross\s*Deductions?\s*[:\s]*([\d,]+\.?\d*)",
        full_text,
        re.IGNORECASE,
    )
    if gross_ded_match:
        data["total_gross_deductions"] = _parse_amount(gross_ded_match.group(1))

    net_match = re.search(
        r"Total\s*Net\s*Earnings?[:\s]*([\d,]+\.?\d*)",
        full_text,
        re.IGNORECASE,
    )
    if net_match:
        data["total_net_earnings"] = _parse_amount(net_match.group(1))

    # --- Extract Cumulative Balances ---
    # These appear as: Cummulative Tax Deduct | Cummulative Income | Cummulative Pension | Cummulative NHF
    # followed by values on the next line
    cum_match = re.search(
        r"Cummulative\s*Tax.*?Cummulative\s*NHF\s*\n?\s*([\d,]+\.?\d*)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if cum_match:
        data["cumulative_tax"] = _parse_amount(cum_match.group(1))
        data["cumulative_income"] = _parse_amount(cum_match.group(2))
        data["cumulative_pension"] = _parse_amount(cum_match.group(3))
        data["cumulative_nhf"] = _parse_amount(cum_match.group(4))

    # --- Extract Earnings Items ---
    # Find text between "Earnings Amount" and "Total<number>" in the earnings section
    earnings_section = re.search(
        r"Earnings\s+Amount\s*\n(.+?)Total\s*([\d,]+\.?\d*)\s*Gross\s*Deductions",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if earnings_section:
        earnings_text = earnings_section.group(1)
        data["earnings"] = _parse_line_items(earnings_text)

    # --- Extract Deduction Items ---
    deductions_section = re.search(
        r"Deductions\s+Amount\s*\n(.+?)Total\s*([\d,]+\.?\d*)",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if deductions_section:
        deductions_text = deductions_section.group(1)
        data["deductions"] = _parse_line_items(deductions_text)

    return data


def _parse_line_items(text):
    """
    Parse earning/deduction line items from a text block.
    Each line has a description followed by an amount.
    """
    items = []
    lines = text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Match: description followed by amount (with optional commas and decimal)
        match = re.match(r"(.+?)\s+([\d,]+\.?\d*)$", line)
        if match:
            item_type = match.group(1).strip()
            amount = _parse_amount(match.group(2))

            if item_type and amount is not None:
                # Skip "Total" lines
                if item_type.lower().startswith("total"):
                    continue
                items.append({"type": item_type, "amount": amount})

    return items


def _parse_amount(amount_str):
    """Parse a formatted amount string (e.g., '257,481.75') into a Decimal."""
    if not amount_str:
        return None
    try:
        cleaned = amount_str.replace(",", "").strip()
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None

