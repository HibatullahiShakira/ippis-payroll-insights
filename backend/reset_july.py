from app import create_app, db
from app.models.payslip import Payslip
from app.models.payslip_earning import PayslipEarning
from app.models.payslip_deduction import PayslipDeduction

app = create_app()

with app.app_context():
    print("Finding payslips for 2026-07...")
    payslips = Payslip.query.filter_by(month_year='2026-07').all()
    payslip_ids = [p.id for p in payslips]
    
    if not payslip_ids:
        print("No payslips found for 2026-07.")
    else:
        print(f"Deleting {len(payslip_ids)} payslips and their earnings/deductions...")
        
        # Delete earnings
        PayslipEarning.query.filter(PayslipEarning.payslip_id.in_(payslip_ids)).delete(synchronize_session=False)
        
        # Delete deductions
        PayslipDeduction.query.filter(PayslipDeduction.payslip_id.in_(payslip_ids)).delete(synchronize_session=False)
        
        # Delete payslips
        Payslip.query.filter(Payslip.id.in_(payslip_ids)).delete(synchronize_session=False)
        
        db.session.commit()
        print("Successfully deleted all 2026-07 payslips.")
