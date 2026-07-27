"""Upload batch model — tracks each monthly file upload."""

from datetime import datetime, timezone
from ..extensions import db


class UploadBatch(db.Model):
    """Represents a single monthly upload of Excel + PDF payslip files."""

    __tablename__ = "upload_batches"

    id = db.Column(db.Integer, primary_key=True)
    month_year = db.Column(db.String(7), nullable=False, index=True)  # e.g. "2026-04"
    excel_filename = db.Column(db.String(300), nullable=True)
    pdf_filename = db.Column(db.String(300), nullable=True)
    total_records = db.Column(db.Integer, default=0)
    records_processed = db.Column(db.Integer, default=0)
    status = db.Column(
        db.String(20), default="pending"
    )  # pending, processing, completed, failed
    error_message = db.Column(db.Text, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    payslips = db.relationship("Payslip", backref="batch", lazy="dynamic")

    def to_dict(self):
        """Serialize batch to dictionary."""
        return {
            "id": self.id,
            "month_year": self.month_year,
            "excel_filename": self.excel_filename,
            "pdf_filename": self.pdf_filename,
            "total_records": self.total_records,
            "records_processed": self.records_processed,
            "status": self.status,
            "error_message": self.error_message,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }
