"""PDF export service — rebuilds payslip PDFs from pages of the uploaded bulk PDFs."""

import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from itertools import groupby

from flask import current_app

from ..extensions import db
from ..models.upload_batch import UploadBatch

STORAGE_BUCKET = "payslips"
DOWNLOAD_TIMEOUT = 120


def storage_object_path(month_year, filename):
    """URL-safe path of a batch PDF inside the Supabase storage bucket."""
    return f"{urllib.parse.quote(month_year)}/{urllib.parse.quote(filename)}"


def safe_filename(name, fallback="file"):
    """Reduce arbitrary text (employee/department names) to a safe download filename part."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_")
    return cleaned or fallback


class PdfSources:
    """
    Resolves each upload batch's original PDF to a file on disk.

    Files that only exist in Supabase are downloaded once per request into a
    temporary directory, which is removed when the context exits.
    """

    def __init__(self):
        self._paths = {}
        self._tmp_dir = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._tmp_dir:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        return False

    def path_for(self, batch_id):
        """Return the local path of the batch's PDF, or None if it cannot be retrieved."""
        if batch_id not in self._paths:
            self._paths[batch_id] = self._resolve(batch_id)
        return self._paths[batch_id]

    def _resolve(self, batch_id):
        batch = db.session.get(UploadBatch, batch_id)
        if not batch or not batch.pdf_filename:
            return None

        local_path = os.path.join(current_app.config["UPLOAD_FOLDER"], batch.month_year, batch.pdf_filename)
        if os.path.exists(local_path):
            return local_path

        supabase_url = current_app.config.get("SUPABASE_URL")
        supabase_key = current_app.config.get("SUPABASE_KEY")
        if not (supabase_url and supabase_key):
            return None

        # Use urllib directly to avoid the supabase-py httpx 5s timeout on large files
        object_path = storage_object_path(batch.month_year, batch.pdf_filename)
        download_url = f"{supabase_url}/storage/v1/object/authenticated/{STORAGE_BUCKET}/{object_path}"
        req = urllib.request.Request(
            download_url,
            headers={"Authorization": f"Bearer {supabase_key}", "apikey": supabase_key},
        )

        if not self._tmp_dir:
            self._tmp_dir = tempfile.mkdtemp(prefix="payslip_src_")
        tmp_path = os.path.join(self._tmp_dir, f"batch_{batch_id}.pdf")
        try:
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as res, open(tmp_path, "wb") as f:
                shutil.copyfileobj(res, f)
        except Exception as e:
            current_app.logger.error(f"Failed to download batch {batch_id} PDF ({object_path}) from cloud: {e}")
            return None
        return tmp_path


def merge_payslip_pages(pages, sources):
    """
    Build one PDF from payslip pages.

    Args:
        pages: Iterable of (batch_id, pdf_page_num) in the desired output order.
        sources: A PdfSources instance.

    Returns:
        (pdf_bytes, page_count) — pdf_bytes is None when no page could be produced.
    """
    import fitz  # PyMuPDF

    out = fitz.open()
    try:
        for batch_id, run in groupby(pages, key=lambda p: p[0]):
            page_nums = [num for _, num in run if num is not None]
            path = sources.path_for(batch_id) if page_nums else None
            if not path:
                continue
            try:
                with fitz.open(path) as src:
                    wanted = [n for n in page_nums if 0 <= n < src.page_count]
                    if wanted:
                        src.select(wanted)
                        out.insert_pdf(src)
            except Exception as e:
                current_app.logger.error(f"Failed to read pages from batch {batch_id} PDF: {e}")

        page_count = out.page_count
        if page_count == 0:
            return None, 0
        # garbage=4 de-duplicates the fonts/logo shared by every payslip page (~6x smaller output)
        return out.tobytes(garbage=4, deflate=True), page_count
    finally:
        out.close()
