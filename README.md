# IPPIS Payroll Insights

A full-stack web application designed to parse, query, and analyze IPPIS SoftSUITE payroll data (Nominal Roll Excel and Bulk Payslip PDFs).

## Features

- **Bulk Upload**: Upload your Nominal Roll (Excel) and bulk Payslips (PDF).
- **Data Parsing**: Automatically extracts employee data, earnings, deductions, and creates database records.
- **Analytics Dashboard**: View salary trends, department payroll costs, Grade Level (GL) distributions, and top deductions.
- **Employee Directory**: Search and filter employees by department, IPPIS number, or GL.
- **Individual Payslips**: View and download single-page payslip PDFs for individual employees.

## Tech Stack

- **Frontend**: React, Vite, Recharts, React Router
- **Backend**: Python, Flask, SQLAlchemy, Flask-JWT-Extended, PyPDF2
- **Database**: SQLite (Development)

## Getting Started Locally

### Backend Setup
1. Navigate to the `backend` directory.
2. Create a virtual environment: `python -m venv venv`
3. Activate it: `.\venv\Scripts\activate` (Windows)
4. Install dependencies: `pip install -r requirements.txt`
5. Run the server: `python run.py`

### Frontend Setup
1. Navigate to the `frontend` directory.
2. Install dependencies: `npm install`
3. Run the dev server: `npm run dev`

## CI/CD Pipeline
This project includes a GitHub Actions workflow (`.github/workflows/ci.yml`) that automatically runs backend tests and builds the frontend on every push to the `main` branch.
