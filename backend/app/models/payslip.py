"""Payslip model — full payslip data parsed from the PDF."""

from ..extensions import db


class Payslip(db.Model):
    """Individual employee payslip for a specific month."""

    __tablename__ = "payslips"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("upload_batches.id"), nullable=False, index=True)
    month_year = db.Column(db.String(7), nullable=False, index=True)
    pdf_page_num = db.Column(db.Integer, nullable=True)

    # Employee info from PDF
    grade = db.Column(db.String(50), nullable=True)
    step = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    tax_state = db.Column(db.String(50), nullable=True)
    designation = db.Column(db.String(200), nullable=True)
    date_of_birth = db.Column(db.String(30), nullable=True)
    date_of_first_appt = db.Column(db.String(30), nullable=True)
    trade_union = db.Column(db.String(100), nullable=True)

    # Bank info
    bank_name = db.Column(db.String(200), nullable=True)
    account_number = db.Column(db.String(30), nullable=True)

    # Pension info
    pfa_name = db.Column(db.String(200), nullable=True)
    pension_pin = db.Column(db.String(50), nullable=True)

    # Summary totals
    total_gross_earnings = db.Column(db.Numeric(12, 2), nullable=True)
    total_gross_deductions = db.Column(db.Numeric(12, 2), nullable=True)
    total_net_earnings = db.Column(db.Numeric(12, 2), nullable=True)

    # Cumulative balances
    cumulative_tax = db.Column(db.Numeric(12, 2), nullable=True)
    cumulative_income = db.Column(db.Numeric(12, 2), nullable=True)
    cumulative_pension = db.Column(db.Numeric(12, 2), nullable=True)
    cumulative_nhf = db.Column(db.Numeric(12, 2), nullable=True)

    # Unique constraint: one payslip per employee per month
    __table_args__ = (
        db.UniqueConstraint("employee_id", "month_year", name="uq_employee_month"),
    )

    # Relationships
    earnings = db.relationship("PayslipEarning", backref="payslip", lazy="joined", cascade="all, delete-orphan")
    deductions = db.relationship("PayslipDeduction", backref="payslip", lazy="joined", cascade="all, delete-orphan")

    def to_dict(self):
        """Full serialization with earnings and deductions."""
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "batch_id": self.batch_id,
            "month_year": self.month_year,
            "grade": self.grade,
            "step": self.step,
            "gender": self.gender,
            "tax_state": self.tax_state,
            "designation": self.designation,
            "date_of_birth": self.date_of_birth,
            "date_of_first_appt": self.date_of_first_appt,
            "trade_union": self.trade_union,
            "bank_name": self.bank_name,
            "account_number": self.account_number,
            "pfa_name": self.pfa_name,
            "pension_pin": self.pension_pin,
            "total_gross_earnings": float(self.total_gross_earnings) if self.total_gross_earnings else None,
            "total_gross_deductions": float(self.total_gross_deductions) if self.total_gross_deductions else None,
            "total_net_earnings": float(self.total_net_earnings) if self.total_net_earnings else None,
            "cumulative_tax": float(self.cumulative_tax) if self.cumulative_tax else None,
            "cumulative_income": float(self.cumulative_income) if self.cumulative_income else None,
            "cumulative_pension": float(self.cumulative_pension) if self.cumulative_pension else None,
            "cumulative_nhf": float(self.cumulative_nhf) if self.cumulative_nhf else None,
            "earnings": [e.to_dict() for e in self.earnings],
            "deductions": [d.to_dict() for d in self.deductions],
        }

    def to_summary_dict(self):
        """Lightweight serialization for list views."""
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "month_year": self.month_year,
            "grade": self.grade,
            "designation": self.designation,
            "total_gross_earnings": float(self.total_gross_earnings) if self.total_gross_earnings else None,
            "total_gross_deductions": float(self.total_gross_deductions) if self.total_gross_deductions else None,
            "total_net_earnings": float(self.total_net_earnings) if self.total_net_earnings else None,
        }
