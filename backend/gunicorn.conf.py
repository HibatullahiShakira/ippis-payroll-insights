"""Gunicorn settings — picked up automatically when gunicorn starts in this folder."""

# Threaded worker: a slow file upload or a long PDF export no longer blocks every
# other request (status polling, page loads) the way the default sync worker does.
worker_class = "gthread"
threads = 4

# Bulk payslip exports download a whole month's PDF from storage before merging;
# the default 30s limit kills the worker mid-request and the browser sees a 502.
timeout = 300
