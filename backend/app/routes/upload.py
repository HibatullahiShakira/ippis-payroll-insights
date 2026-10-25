"""
Upload routes — Excel + PDF uploads in two steps.

1. POST /upload saves the files to a holding folder and analyses them in the
   background without touching any data (status: analyzing -> awaiting_review).
2. The user reviews the report and either confirms (POST /uploads/<id>/confirm,
   status: processing -> completed) or cancels (POST /uploads/<id>/cancel).

Files only move into the month's folder (and cloud storage) once confirmed, so a
cancelled or mistaken upload never replaces the PDF an existing month relies on.
"""

import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models.employee_history import EmployeeHistory
from ..models.upload_batch import UploadBatch
from ..models.upload_report import UploadReport
from ..models.payslip import Payslip
from ..models.payslip_earning import PayslipEarning
from ..models.payslip_deduction import PayslipDeduction
from ..services.excel_parser import month_from_filename, parse_excel
from ..services.pdf_parser import parse_pdf, detect_month_year
from ..services.pdf_export import STORAGE_BUCKET, PdfSources, storage_object_path
from ..services.upload_review import build_report, load_report, save_report
from ..utils import admin_required, is_valid_month_year

upload_bp = Blueprint("upload", __name__)

ALLOWED_EXCEL = {".xlsx", ".xls"}
ALLOWED_PDF = {".pdf"}

# A batch stuck analysing/importing this long was cut off by a server restart
STALE_AFTER = timedelta(minutes=30)


def allowed_file(filename, allowed_extensions):
    """Check if file has an allowed extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in allowed_extensions


def _pending_dir(batch_id, upload_folder=None):
    """Holding folder for an upload's files until it is confirmed."""
    return os.path.join(upload_folder or current_app.config["UPLOAD_FOLDER"], "pending", str(batch_id))


def _pending_paths(batch, upload_folder=None):
    folder = _pending_dir(batch.id, upload_folder)
    excel = os.path.join(folder, batch.excel_filename) if batch.excel_filename else None
    pdf = os.path.join(folder, batch.pdf_filename) if batch.pdf_filename else None
    return excel, pdf


def _start_background(target, *args):
    app = current_app._get_current_object()
    thread = threading.Thread(target=target, args=(app, *args))
    thread.daemon = True
    thread.start()


def _expire_if_stale(batch):
    """Mark a batch failed if the server restarted while it was being worked on."""
    if batch.status not in ("analyzing", "processing") or not batch.uploaded_at:
        return
    started = batch.uploaded_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - started > STALE_AFTER:
        stage = "checking" if batch.status == "analyzing" else "importing"
        batch.status = "failed"
        batch.error_message = (
            f"The server restarted while {stage} this upload, so it did not finish. Please upload the files again."
        )
        db.session.commit()


@upload_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_files():
    """Receive Excel and/or PDF payslip files and start checking them; nothing is imported yet."""
    user_id = get_jwt_identity()
    # Optional: the month is normally read from the payslip PDF itself
    month_year = request.form.get("month_year", "").strip()

    # month_year becomes a folder name, so it must be strictly validated
    if month_year and not is_valid_month_year(month_year):
        return jsonify({"error": "'month_year' must be in YYYY-MM format (e.g., '2026-04')"}), 400

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

    # Files land in a staging folder first: the month is only known once the PDF is read
    staging_dir = tempfile.mkdtemp(prefix="incoming_", dir=current_app.config["UPLOAD_FOLDER"])
    try:
        excel_filename = pdf_filename = None
        if has_excel:
            excel_filename = secure_filename(excel_file.filename) or "nominal_roll.xlsx"
            excel_file.save(os.path.join(staging_dir, excel_filename))

        if has_pdf:
            pdf_filename = secure_filename(pdf_file.filename) or "payslips.pdf"
            staged_pdf = os.path.join(staging_dir, pdf_filename)
            pdf_file.save(staged_pdf)
            try:
                # The month printed on the payslips wins over anything sent by the client
                month_year = detect_month_year(staged_pdf) or month_year
            except Exception:
                return jsonify({"error": "The PDF file could not be read. Please check it is a valid payslip PDF."}), 400
            if not month_year:
                return jsonify({
                    "error": "Could not find the payroll month and year on the payslips in this PDF."
                }), 400
        elif not month_year:
            # A nominal roll on its own: use the month in its file name, else the current month
            month_year = month_from_filename(excel_filename) or datetime.now(timezone.utc).strftime("%Y-%m")

        batch = UploadBatch(
            month_year=month_year,
            excel_filename=excel_filename,
            pdf_filename=pdf_filename,
            uploaded_by=int(user_id),
            status="analyzing",
        )
        db.session.add(batch)
        db.session.commit()

        # Hold the files aside until the upload is reviewed and confirmed
        pending = _pending_dir(batch.id)
        shutil.rmtree(pending, ignore_errors=True)
        os.makedirs(os.path.dirname(pending), exist_ok=True)
        os.replace(staging_dir, pending)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    _start_background(_analyze_upload, batch.id)

    return jsonify({
        "message": "Upload received — checking the files before import",
        "batch": batch.to_dict(),
    }), 202


def _analyze_upload(app, batch_id, reprocess=False):
    """Background task: read the files without importing anything and store the review report."""
    with app.app_context():
        try:
            batch = db.session.get(UploadBatch, batch_id)
            excel, pdf = _pending_paths(batch, app.config["UPLOAD_FOLDER"])
            report = build_report(batch.month_year, excel_path=excel, pdf_path=pdf, reprocess=reprocess)
            save_report(batch_id, report)
            # Everything the import will save: nominal-roll rows, then payslips
            batch.total_records = (
                ((report.get("excel") or {}).get("rows") or 0) + ((report.get("pdf") or {}).get("payslips") or 0)
            )
            batch.status = "awaiting_review"
            db.session.commit()
        except Exception as e:
            app.logger.exception(f"Checking upload batch {batch_id} failed")
            db.session.rollback()
            batch = db.session.get(UploadBatch, batch_id)
            if batch:
                batch.status = "failed"
                batch.error_message = f"The files could not be checked: {e}"
                db.session.commit()
        finally:
            db.session.remove()


@upload_bp.route("/uploads/<int:batch_id>/confirm", methods=["POST"])
@jwt_required()
def confirm_upload(batch_id):
    """Import an upload that has been reviewed."""
    batch = UploadBatch.query.get_or_404(batch_id)
    if batch.status != "awaiting_review":
        return jsonify({"error": f"This upload cannot be imported (status: {batch.status})."}), 409

    report = load_report(batch_id) or {}
    if not report.get("can_import"):
        return jsonify({"error": "This upload has errors and cannot be imported. Fix the files and upload again."}), 409

    pending_excel, pending_pdf = _pending_paths(batch)
    if any(p and not os.path.exists(p) for p in (pending_excel, pending_pdf)):
        batch.status = "failed"
        batch.error_message = "The uploaded files are no longer on the server (it restarted). Please upload again."
        db.session.commit()
        return jsonify({"error": batch.error_message}), 410

    # Only now do the files replace the ones the month's existing records rely on
    month_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], batch.month_year)
    os.makedirs(month_dir, exist_ok=True)
    excel_path = pdf_path = None
    if pending_excel:
        excel_path = os.path.join(month_dir, batch.excel_filename)
        os.replace(pending_excel, excel_path)
    if pending_pdf:
        pdf_path = os.path.join(month_dir, batch.pdf_filename)
        os.replace(pending_pdf, pdf_path)
    shutil.rmtree(_pending_dir(batch_id), ignore_errors=True)

    batch.status = "processing"
    batch.records_processed = 0
    # Restart the stale-upload clock for the import step
    batch.uploaded_at = datetime.now(timezone.utc)
    db.session.commit()

    _start_background(_process_upload, batch.id, excel_path, pdf_path, batch.month_year)
    return jsonify({"message": "Import started", "batch": batch.to_dict()}), 202


@upload_bp.route("/uploads/<int:batch_id>/reprocess", methods=["POST"])
@jwt_required()
def reprocess_upload(batch_id):
    """
    Read a previously imported payslip PDF again with the current parser.

    The stored PDF is copied into a new upload and goes through the same review
    step as a fresh upload, so nothing changes until the user confirms.
    """
    source = UploadBatch.query.get_or_404(batch_id)
    if source.status != "completed" or not source.pdf_filename:
        return jsonify({"error": "Only a completed upload that included a payslip PDF can be re-processed."}), 409

    batch = None
    with PdfSources() as sources:
        source_path = sources.path_for(source.id)
        if not source_path:
            return jsonify({
                "error": "The original PDF for this upload is no longer stored, so it cannot be re-processed. "
                         "Upload the PDF again instead."
            }), 404

        # Trust the month printed on the payslips over what the old upload was filed under
        try:
            month_year = detect_month_year(source_path) or source.month_year
        except Exception:
            return jsonify({"error": "The stored PDF could not be read."}), 422

        batch = UploadBatch(
            month_year=month_year,
            pdf_filename=source.pdf_filename,
            uploaded_by=int(get_jwt_identity()),
            status="analyzing",
        )
        db.session.add(batch)
        db.session.commit()

        pending = _pending_dir(batch.id)
        os.makedirs(pending, exist_ok=True)
        shutil.copyfile(source_path, os.path.join(pending, batch.pdf_filename))

    _start_background(_analyze_upload, batch.id, True)
    return jsonify({
        "message": f"Re-reading the {source.month_year} payslip PDF — review the result before it is imported",
        "batch": batch.to_dict(),
    }), 202


@upload_bp.route("/uploads/<int:batch_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_upload(batch_id):
    """Discard an upload that has not been imported."""
    batch = UploadBatch.query.get_or_404(batch_id)
    if batch.status not in ("awaiting_review", "failed"):
        return jsonify({"error": f"This upload cannot be cancelled (status: {batch.status})."}), 409
    shutil.rmtree(_pending_dir(batch_id), ignore_errors=True)
    if batch.status == "awaiting_review":
        batch.status = "cancelled"
    db.session.commit()
    return jsonify({"message": "Upload discarded", "batch": batch.to_dict()})


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

            # Parse PDF (creates Payslip records linked to Employees);
            # progress keeps counting on from the nominal roll
            if pdf_path:
                pdf_count = parse_pdf(pdf_path, batch_id, month_year, progress_offset=total)
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
    for batch in batches:
        _expire_if_stale(batch)
    return jsonify({"uploads": [b.to_dict() for b in batches]})


@upload_bp.route("/uploads/<int:batch_id>/status", methods=["GET"])
@jwt_required()
def upload_status(batch_id):
    """Check the status of an upload batch, with its review report once the files are checked."""
    batch = UploadBatch.query.get_or_404(batch_id)
    _expire_if_stale(batch)
    return jsonify({"batch": batch.to_dict(), "report": load_report(batch_id)})


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

        # The month's uploads, plus nominal-roll-only uploads named for this month (older ones
        # were filed under their upload month), so the month can be uploaded afresh
        batch_ids = {b.id for b in UploadBatch.query.filter_by(month_year=month_year)}
        batch_ids |= {
            b.id for b in UploadBatch.query.filter(UploadBatch.pdf_filename.is_(None), UploadBatch.excel_filename.isnot(None))
            if month_from_filename(b.excel_filename) == month_year
        }
        batch_ids = list(batch_ids)
        if batch_ids:
            load_report(batch_ids[0])  # makes sure the reports table exists before deleting from it
            UploadReport.query.filter(UploadReport.batch_id.in_(batch_ids)).delete(synchronize_session=False)
            EmployeeHistory.query.filter(EmployeeHistory.batch_id.in_(batch_ids)).update(
                {EmployeeHistory.batch_id: None}, synchronize_session=False
            )
            UploadBatch.query.filter(UploadBatch.id.in_(batch_ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"message": f"Deleted all data for {month_year}. It can now be uploaded again."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
