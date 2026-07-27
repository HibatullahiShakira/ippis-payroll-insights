import pytest
from sqlalchemy.exc import IntegrityError
from app.models.employee import Employee
from app.models.payslip import Payslip
from app.models.payslip_earning import PayslipEarning
from app.models.payslip_deduction import PayslipDeduction
from app.models.upload_batch import UploadBatch
from app.extensions import db

def test_employee_creation(db_session):
    """Test creating an employee."""
    emp = Employee(
        file_no=12345,
        ippis_number=12345,
        name="John Doe",
        department="Engineering",
        division="Software",
        gl="09"
    )
    db_session.add(emp)
    db_session.commit()
    
    assert emp.id is not None
    assert emp.file_no == 12345

def test_payslip_relationships(db_session):
    """Test that payslips can have earnings and deductions attached."""
    batch = UploadBatch(month_year="2026-04", status="completed")
    emp = Employee(file_no=111, ippis_number=111, name="Jane Doe")
    db_session.add_all([batch, emp])
    db_session.commit()
    
    payslip = Payslip(
        employee_id=emp.id,
        batch_id=batch.id,
        month_year="2026-04",
        grade="09",
        step="2",
        total_gross_earnings=100000.0,
        total_gross_deductions=10000.0,
        total_net_earnings=90000.0
    )
    
    earning = PayslipEarning(
        payslip=payslip,
        earning_type="Basic Salary",
        amount=100000.0
    )
    
    deduction = PayslipDeduction(
        payslip=payslip,
        deduction_type="Tax",
        amount=10000.0
    )
    
    db_session.add_all([payslip, earning, deduction])
    db_session.commit()
    
    # Reload and test relationship properties
    reloaded_emp = Employee.query.first()
    payslips = list(reloaded_emp.payslips)
    assert len(payslips) == 1
    assert payslips[0].month_year == "2026-04"
    assert len(list(payslips[0].earnings)) == 1
    assert len(list(payslips[0].deductions)) == 1
    assert list(payslips[0].earnings)[0].amount == 100000.0

def test_payslip_unique_constraint(db_session):
    """Test that an employee cannot have two payslips for the same month."""
    batch = UploadBatch(month_year="2026-05", status="completed")
    emp = Employee(file_no=222, ippis_number=222, name="Bob")
    db_session.add_all([batch, emp])
    db_session.commit()
    
    payslip1 = Payslip(employee_id=emp.id, batch_id=batch.id, month_year="2026-05")
    db_session.add(payslip1)
    db_session.commit()
    
    payslip2 = Payslip(employee_id=emp.id, batch_id=batch.id, month_year="2026-05")
    db_session.add(payslip2)
    
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
