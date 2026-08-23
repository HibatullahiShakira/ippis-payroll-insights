import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS employee_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    batch_id INTEGER,
    old_gl VARCHAR(10),
    old_department VARCHAR(200),
    old_division VARCHAR(200),
    new_gl VARCHAR(10),
    new_department VARCHAR(200),
    new_division VARCHAR(200),
    change_date DATETIME,
    FOREIGN KEY(employee_id) REFERENCES employees(id),
    FOREIGN KEY(batch_id) REFERENCES upload_batches(id)
)
''')
conn.commit()
print("Table created.")
conn.close()
