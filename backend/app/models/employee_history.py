"""EmployeeHistory model — tracks changes to employee department, division, and grade."""

from datetime import datetime, timezone
from ..extensions import db


class EmployeeHistory(db.Model):
    """Tracks historical changes to an employee's department, division, and grade."""

    __tablename__ = "employee_history"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("upload_batches.id"), nullable=True, index=True)
    
    # Old values
    old_gl = db.Column(db.String(10), nullable=True)
    old_department = db.Column(db.String(200), nullable=True)
    old_division = db.Column(db.String(200), nullable=True)
    
    # New values
    new_gl = db.Column(db.String(10), nullable=True)
    new_department = db.Column(db.String(200), nullable=True)
    new_division = db.Column(db.String(200), nullable=True)
    
    change_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    employee = db.relationship("Employee", backref=db.backref("history", lazy="dynamic", cascade="all, delete-orphan"))
    batch = db.relationship("UploadBatch")

    def to_dict(self):
        """Serialize history record to dictionary."""
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "batch_id": self.batch_id,
            "old_gl": self.old_gl,
            "old_department": self.old_department,
            "old_division": self.old_division,
            "new_gl": self.new_gl,
            "new_department": self.new_department,
            "new_division": self.new_division,
            "change_date": self.change_date.isoformat() if self.change_date else None,
            "month_year": self.batch.month_year if self.batch else None
        }
