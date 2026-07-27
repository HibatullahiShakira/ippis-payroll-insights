import pytest
from app.models.employee import Employee
from app.models.payslip import Payslip

def test_get_employees_unauthenticated(client):
    """Ensure API endpoints are protected."""
    response = client.get('/api/employees')
    assert response.status_code == 401

def test_get_employees(client, db_session, auth_headers):
    """Test fetching the employee directory."""
    emp1 = Employee(file_no="1", name="Alice", department="HR", ippis_number=111)
    emp2 = Employee(file_no="2", name="Bob", department="Engineering", ippis_number=222)
    db_session.add_all([emp1, emp2])
    db_session.commit()
    
    response = client.get('/api/employees', headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["employees"]) == 2
    assert data["pagination"]["total"] == 2

def test_search_employees(client, db_session, auth_headers):
    """Test filtering employees."""
    emp1 = Employee(file_no="1", name="Alice", department="HR", ippis_number=333)
    emp2 = Employee(file_no="2", name="Bob", department="Engineering", ippis_number=444)
    db_session.add_all([emp1, emp2])
    db_session.commit()
    
    response = client.get('/api/employees?department=HR', headers=auth_headers)
    data = response.get_json()
    assert len(data["employees"]) == 1
    assert data["employees"][0]["name"] == "Alice"

def test_analytics_overview(client, db_session, auth_headers):
    """Test the analytics monthly overview endpoint."""
    from app.models.upload_batch import UploadBatch
    batch = UploadBatch(month_year="2026-04", status="completed")
    emp = Employee(file_no="1", name="Alice", ippis_number=555)
    db_session.add_all([batch, emp])
    db_session.commit()
    
    payslip = Payslip(
        employee_id=emp.id,
        batch_id=batch.id,
        month_year="2026-04",
        total_gross_earnings=100.0,
        total_gross_deductions=10.0,
        total_net_earnings=90.0
    )
    db_session.add(payslip)
    db_session.commit()
    
    response = client.get('/api/analytics/monthly-overview', headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    
    assert len(data["months"]) == 1
    month_data = data["months"][0]
    assert month_data["month_year"] == "2026-04"
    assert month_data["employee_count"] == 1
    assert month_data["total_earnings"] == 100.0
    assert month_data["total_net"] == 90.0
