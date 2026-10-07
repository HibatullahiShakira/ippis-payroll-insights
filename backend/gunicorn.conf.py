"""Gunicorn settings — picked up automatically when gunicorn starts in this folder."""

# Bulk payslip exports download a whole month's PDF from storage before merging;
# the default 30s limit kills the worker mid-request and the browser sees a 502.
timeout = 300
