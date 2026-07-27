"""Payslip earning line item model."""

from ..extensions import db


class PayslipEarning(db.Model):
    """Individual earning line on a payslip (e.g., Consolidated Salary, Peculiar Allowance)."""

    __tablename__ = "payslip_earnings"

    id = db.Column(db.Integer, primary_key=True)
    payslip_id = db.Column(db.Integer, db.ForeignKey("payslips.id"), nullable=False, index=True)
    earning_type = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "earning_type": self.earning_type,
            "amount": float(self.amount) if self.amount else 0,
        }
