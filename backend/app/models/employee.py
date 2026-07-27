"""Employee model — master record from the nominal payroll Excel."""

from datetime import datetime, timezone
from ..extensions import db


class Employee(db.Model):
    """Employee master record parsed from the nominal payroll sheet."""

    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    serial_no = db.Column(db.Integer, nullable=True)
    file_no = db.Column(db.Integer, nullable=False, index=True)
    ippis_number = db.Column(db.Integer, nullable=False, unique=True, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    gl = db.Column(db.String(10), nullable=True, index=True)
    department = db.Column(db.String(200), nullable=True, index=True)
    division = db.Column(db.String(200), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    payslips = db.relationship("Payslip", backref="employee", lazy="dynamic")

    def to_dict(self):
        """Serialize employee to dictionary."""
        return {
            "id": self.id,
            "serial_no": self.serial_no,
            "file_no": self.file_no,
            "ippis_number": self.ippis_number,
            "name": self.name,
            "gl": self.gl,
            "department": self.department,
            "division": self.division,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_summary_dict(self):
        """Lightweight serialization for list views."""
        return {
            "id": self.id,
            "file_no": self.file_no,
            "ippis_number": self.ippis_number,
            "name": self.name,
            "gl": self.gl,
            "department": self.department,
            "division": self.division,
        }
