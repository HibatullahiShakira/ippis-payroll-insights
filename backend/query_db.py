import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()
cursor.execute("SELECT id, month_year, excel_filename, pdf_filename, status, error_message FROM upload_batches ORDER BY id DESC LIMIT 5;")
print("Last 5 batches:")
for row in cursor.fetchall():
    print(row)
conn.close()
