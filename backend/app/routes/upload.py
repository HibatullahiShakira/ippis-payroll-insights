"""Upload routes — handle Excel + PDF file upload and trigger parsing."""

import os
import threading
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename

from ..extensions import db, get_supabase
from ..models.upload_batch import UploadBatch
from ..models.payslip import Payslip
from ..models.payslip_earning import PayslipEarning
from ..models.payslip_deduction import PayslipDeduction
from ..services.excel_parser import parse_excel
from ..services.pdf_parser import parse_pdf

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
    month_year = request.form.get("month_year")

    if not month_year:
        return jsonify({"error": "'month_year' is required (e.g., '2026-04')"}), 400

    excel_file = request.files.get("excel_file")
    pdf_file = request.files.get("pdf_file")

    if not excel_file and not pdf_file:
        return jsonify({"error": "At least one file (Excel or PDF) is required"}), 400

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
    if excel_file and excel_file.filename:
        if not allowed_file(excel_file.filename, ALLOWED_EXCEL):
            return jsonify({"error": "Excel file must be .xlsx or .xls"}), 400
        excel_filename = secure_filename(excel_file.filename)
        excel_path = os.path.join(upload_dir, excel_filename)
        excel_file.save(excel_path)
        batch.excel_filename = excel_filename

    # Save PDF file
    pdf_path = None
    if pdf_file and pdf_file.filename:
        if not allowed_file(pdf_file.filename, ALLOWED_PDF):
            return jsonify({"error": "PDF file must be .pdf"}), 400
        pdf_filename = secure_filename(pdf_file.filename)
        pdf_path = os.path.join(upload_dir, pdf_filename)
        pdf_file.save(pdf_path)
        batch.pdf_filename = pdf_filename
        
        # Upload to Supabase
        supabase = get_supabase()
        if supabase:
            try:
                storage_path = f"{month_year}/{pdf_filename}"
                with open(pdf_path, 'rb') as f:
                    supabase.storage.from_("payslips").upload(
                        file=f,
                        path=storage_path,
                        file_options={"content-type": "application/pdf"}
                    )
            except Exception as e:
                if "already" in str(e).lower() or "duplicate" in str(e).lower():
                    try:
                        with open(pdf_path, 'rb') as f:
                            supabase.storage.from_("payslips").update(
                                file=f,
                                path=storage_path,
                                file_options={"content-type": "application/pdf"}
                            )
                    except Exception as e2:
                        print(f"Supabase update failed: {e2}")
                else:
                    print(f"Supabase upload failed: {e}")

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
        batch = UploadBatch.query.get(batch_id)
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
            db.session.commit()

        except Exception as e:
            batch.status = "failed"
            batch.error_message = str(e)
            db.session.commit()
        finally:
            # Cleanup temporary files if uploaded to Supabase
            if get_supabase():
                try:
                    if pdf_path and os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    if excel_path and os.path.exists(excel_path):
                        os.remove(excel_path)
                except Exception as e:
                    print(f"Failed to cleanup temp files: {e}")


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
@jwt_required()
def delete_month_data(month_year):
    """Delete all payslips, earnings, deductions, and batches for a specific month_year."""
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
