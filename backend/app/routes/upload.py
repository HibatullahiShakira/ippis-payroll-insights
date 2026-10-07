"""Upload routes — handle Excel + PDF file upload and trigger parsing."""

import os
import threading
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models.upload_batch import UploadBatch
from ..models.payslip import Payslip
from ..models.payslip_earning import PayslipEarning
from ..models.payslip_deduction import PayslipDeduction
from ..services.excel_parser import parse_excel
from ..services.pdf_parser import parse_pdf
from ..services.pdf_export import STORAGE_BUCKET, storage_object_path
from ..utils import admin_required, is_valid_month_year

upload_bp = Blueprint("upload", __name__)

ALLOWED_EXCEL = {".xlsx", ".xls"}
ALLOWED_PDF = {".pdf"}


def allowed_file(filename, allowed_extensions):
    """Check if file has an allowed extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in allowed_extensions


@upload_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_files():
    """Upload Excel and/or PDF payslip files for a given month."""
    user_id = get_jwt_identity()
    month_year = request.form.get("month_year", "").strip()

    # month_year becomes a folder name, so it must be strictly validated
    if not is_valid_month_year(month_year):
        return jsonify({"error": "'month_year' is required in YYYY-MM format (e.g., '2026-04')"}), 400

    excel_file = request.files.get("excel_file")
    pdf_file = request.files.get("pdf_file")
    has_excel = bool(excel_file and excel_file.filename)
    has_pdf = bool(pdf_file and pdf_file.filename)

    if not has_excel and not has_pdf:
        return jsonify({"error": "At least one file (Excel or PDF) is required"}), 400

    # Validate both files before anything is written to disk
    if has_excel and not allowed_file(excel_file.filename, ALLOWED_EXCEL):
        return jsonify({"error": "Excel file must be .xlsx or .xls"}), 400
    if has_pdf and not allowed_file(pdf_file.filename, ALLOWED_PDF):
        return jsonify({"error": "PDF file must be .pdf"}), 400

    # Create upload directory for this batch
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], month_year)
    os.makedirs(upload_dir, exist_ok=True)

    # Create batch record
    batch = UploadBatch(
        month_year=month_year,
        uploaded_by=int(user_id),
        status="processing",
    )

    # Save Excel file
    excel_path = None
    if has_excel:
        excel_filename = secure_filename(excel_file.filename) or "nominal_roll.xlsx"
        excel_path = os.path.join(upload_dir, excel_filename)
        excel_file.save(excel_path)
        batch.excel_filename = excel_filename

    # Save PDF file
    pdf_path = None
    if has_pdf:
        pdf_filename = secure_filename(pdf_file.filename) or "payslips.pdf"
        pdf_path = os.path.join(upload_dir, pdf_filename)
        pdf_file.save(pdf_path)
        batch.pdf_filename = pdf_filename


    db.session.add(batch)
    db.session.commit()

    # Process files in background thread
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_process_upload,
        args=(app, batch.id, excel_path, pdf_path, month_year),
    )
    thread.daemon = True
    thread.start()

    return jsonify({
        "message": "Upload started — processing in background",
        "batch": batch.to_dict(),
    }), 202


def _process_upload(app, batch_id, excel_path, pdf_path, month_year):
    """Background task to parse uploaded files."""
    with app.app_context():
        batch = db.session.get(UploadBatch, batch_id)

        supabase_url = app.config.get("SUPABASE_URL")
        supabase_key = app.config.get("SUPABASE_KEY")
        pdf_stored_in_cloud = False
        storage_warning = None
        if pdf_path and os.path.exists(pdf_path) and supabase_url and supabase_key:
            try:
                import urllib.request
                object_path = storage_object_path(month_year, os.path.basename(pdf_path))
                upload_url = f"{supabase_url}/storage/v1/object/{STORAGE_BUCKET}/{object_path}"
                with open(pdf_path, 'rb') as f:
                    req = urllib.request.Request(
                        upload_url,
                        data=f.read(),
                        headers={
                            "Authorization": f"Bearer {supabase_key}",
                            "apikey": supabase_key,
                            "Content-Type": "application/pdf",
                            # Replace the file if this month was uploaded before
                            "x-upsert": "true",
                        },
                        method="POST"
                    )
                with urllib.request.urlopen(req, timeout=300):
                    pass
                pdf_stored_in_cloud = True
            except Exception as e:
                app.logger.error(f"Supabase upload failed for batch {batch_id}: {e}")
                storage_warning = (
                    "Records were processed, but the PDF could not be saved to cloud storage, "
                    f"so payslip PDF downloads may be unavailable for this month ({e})."
                )

        try:
            total = 0

            # Parse Excel first (creates/updates Employee records)
            if excel_path:
                excel_count = parse_excel(excel_path, batch_id)
                total += excel_count

            # Parse PDF (creates Payslip records linked to Employees)
            if pdf_path:
                pdf_count = parse_pdf(pdf_path, batch_id, month_year)
                total += pdf_count

            batch.total_records = total
            batch.records_processed = total
            batch.status = "completed"
            batch.error_message = storage_warning
            db.session.commit()

        except Exception as e:
            app.logger.exception(f"Processing upload batch {batch_id} failed")
            db.session.rollback()
            batch = db.session.get(UploadBatch, batch_id)
            if batch:
                batch.status = "failed"
                batch.error_message = str(e)
                db.session.commit()
        finally:
            # Cleanup temporary files if uploaded to Supabase.
            # The PDF is kept locally when the cloud copy failed, so it stays downloadable.
            if supabase_url and supabase_key:
                try:
                    if pdf_stored_in_cloud and os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    if excel_path and os.path.exists(excel_path):
                        os.remove(excel_path)
                except Exception as e:
                    app.logger.warning(f"Failed to cleanup temp files: {e}")
            db.session.remove()


@upload_bp.route("/uploads", methods=["GET"])
@jwt_required()
def list_uploads():
    """List all upload batches."""
    batches = UploadBatch.query.order_by(UploadBatch.uploaded_at.desc()).all()
    return jsonify({"uploads": [b.to_dict() for b in batches]})


@upload_bp.route("/uploads/<int:batch_id>/status", methods=["GET"])
@jwt_required()
def upload_status(batch_id):
    """Check the processing status of an upload batch."""
    batch = UploadBatch.query.get_or_404(batch_id)
    return jsonify({"batch": batch.to_dict()})


@upload_bp.route("/uploads/month/<month_year>", methods=["DELETE"])
@admin_required
def delete_month_data(month_year):
    """Delete all payslips, earnings, deductions, and batches for a specific month_year (admin only)."""
    if not is_valid_month_year(month_year):
        return jsonify({"error": "month_year must be in YYYY-MM format"}), 400
    try:
        payslips = Payslip.query.filter_by(month_year=month_year).all()
        payslip_ids = [p.id for p in payslips]
        
        if payslip_ids:
            PayslipEarning.query.filter(PayslipEarning.payslip_id.in_(payslip_ids)).delete(synchronize_session=False)
            PayslipDeduction.query.filter(PayslipDeduction.payslip_id.in_(payslip_ids)).delete(synchronize_session=False)
            Payslip.query.filter(Payslip.id.in_(payslip_ids)).delete(synchronize_session=False)
            
        UploadBatch.query.filter_by(month_year=month_year).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"message": f"Successfully deleted all data for {month_year}."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
