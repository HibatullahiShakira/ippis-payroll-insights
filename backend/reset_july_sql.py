import sqlite3

conn = sqlite3.connect('payroll.db')
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM payslips WHERE month_year='2026-07'")
count = c.fetchone()[0]

if count > 0:
    print(f"Deleting {count} payslips and their earnings/deductions...")
    c.execute("DELETE FROM payslip_earnings WHERE payslip_id IN (SELECT id FROM payslips WHERE month_year='2026-07')")
    c.execute("DELETE FROM payslip_deductions WHERE payslip_id IN (SELECT id FROM payslips WHERE month_year='2026-07')")
    c.execute("DELETE FROM payslips WHERE month_year='2026-07'")
    conn.commit()
    print("Deleted successfully.")
else:
    print("No payslips found for 2026-07.")

conn.close()
