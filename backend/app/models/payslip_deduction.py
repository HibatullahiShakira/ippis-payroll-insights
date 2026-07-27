"""Payslip deduction line item model."""

from ..extensions import db


class PayslipDeduction(db.Model):
    """Individual deduction line on a payslip (e.g., Tax, Pension, NHF, Cooperative)."""

    __tablename__ = "payslip_deductions"

    id = db.Column(db.Integer, primary_key=True)
    payslip_id = db.Column(db.Integer, db.ForeignKey("payslips.id"), nullable=False, index=True)
    deduction_type = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "deduction_type": self.deduction_type,
            "amount": float(self.amount) if self.amount else 0,
        }
