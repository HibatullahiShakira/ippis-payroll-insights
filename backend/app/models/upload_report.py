"""Upload report model — the pre-import quality check of an upload batch."""

import json
from datetime import datetime, timezone

from ..extensions import db


class UploadReport(db.Model):
    """What the system found in an upload's files before anything was imported."""

    __tablename__ = "upload_reports"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("upload_batches.id"), nullable=False, unique=True, index=True)
    report_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def report(self):
        return json.loads(self.report_json)

    @report.setter
    def report(self, value):
        self.report_json = json.dumps(value, default=str)
