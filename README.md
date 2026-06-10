# Automatic Student Attendance Shortage Monitoring System (AMS)

A web-based attendance management system that automates the complete attendance shortage workflow — uploading Excel records, identifying at-risk students below a configurable threshold, dispatching personalised SMS alerts to parents via Twilio, and generating downloadable Excel and PDF shortage letter reports — with full per-faculty data persistence across login sessions.


---

## Overview

Faculty members export attendance records from any Student Information System as an `.xlsx` file and upload it to the AMS. The system automatically normalises attendance percentage values, applies the configured range filter, identifies at-risk students, and makes them available for SMS notification and report download. All data — upload history, SMS delivery logs, and download records — is stored per faculty in a local SQLite database and restored on every login, ensuring complete session continuity.

---

## How It Works

```
1. Faculty logs in  →  session created (faculty_id, role)
          ↓
2. Upload .xlsx attendance file + select attendance range
          ↓
3. Pandas reads file  →  normalises Present % column
   (decimal values 0–1 are multiplied by 100 automatically)
          ↓
4. Filters students within the specified attendance range
   (default: 0% – 75%)
          ↓
5. Filtered records stored per faculty in ams.db (JSON snapshot)
   Filtered Excel saved to outputs/faculty_{id}_below75.xlsx
          ↓
6. PDF shortage letters generated per student via pdfkit + template.html
   PDF saved to outputs/faculty_{id}_shortage.pdf
          ↓
7. Faculty sends SMS alerts via Twilio to parent phones (from students.db)
   Each message includes student name, roll number, and actual attendance %
          ↓
8. Faculty downloads Excel and/or PDF reports
          ↓
9. All history (uploads, SMS logs, downloads) restored on next login
```

---

## Features

- **Secure Faculty Login** — Role-based access (Faculty / Admin) with bcrypt password hashing via Werkzeug
- **Excel Upload** — Accepts `.xlsx` attendance files exported from any Student Information System
- **Attendance Range Filter** — Configurable lower and upper bounds (e.g. 0–75%, 25–50%, 65–75%)
- **Auto Normalisation** — Handles both decimal (0–1) and percentage (0–100) forms of Present % automatically
- **Twilio SMS Alerts** — Dispatches personalised SMS to parents including student name, roll number, and actual attendance percentage
- **PDF Shortage Letters** — Generates individual GNITS-format shortage letters per student using pdfkit and a custom HTML template
- **Excel Report** — Downloads filtered at-risk student list as `.xlsx`
- **Per-Faculty Data Persistence** — Upload history, SMS logs, and download history stored in SQLite and restored on login
- **Admin Panel** — Add, delete, and reset passwords for faculty accounts
- **Responsive Dashboard** — Single-page interface with drag-and-drop upload, live SMS delivery log, analytics with KPI cards, and download history

---

## SMS Notification Format

```
GNITS: Dear Parent, This is to inform you that your ward,
{Name} (Roll No: {Roll No.}), has an attendance of {XX.XX%}
which is below 75% this month. Kindly ensure regular attendance.
Regards, HOD CSE GNITS
```

**Example:**

```
GNITS: Dear Parent, This is to inform you that your ward,
P. Keerthana (Roll No: 23251A05J2), has an attendance of
58.10% which is below 75% this month. Kindly ensure regular
attendance. Regards, HOD CSE GNITS
```

- Sender number: Twilio registered number (`+12603669043`)
- Recipient prefix: `+91` (India)
- Phone numbers looked up from `students.db` by Roll No.
- Duplicate prevention: a student cannot receive more than one SMS per upload session

---

## System Architecture

The AMS follows a three-tier architecture:

| Tier | Components |
|---|---|
| **Presentation Layer** | `login.html` (faculty authentication), `index.html` (multi-screen dashboard) — served by Flask + Jinja2 |
| **Application Logic Layer** | Flask routes for upload, filtering, SMS dispatch, data retrieval, file download; Pandas for data processing; Twilio client for SMS |
| **Data Layer** | `ams.db` — faculty accounts, upload history, at-risk snapshots, SMS logs, download history; `students.db` — parent phone number lookup |

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend Framework | Python, Flask |
| Data Processing | Pandas, openpyxl |
| Database | SQLite (`ams.db`, `students.db`) |
| SMS Gateway | Twilio REST API |
| PDF Generation | pdfkit + wkhtmltopdf |
| Password Security | Werkzeug (bcrypt hashing) |
| Frontend | HTML5, CSS3, JavaScript ES6 (Fetch API) |
| Version Control | Git / GitHub |

---

## Project Structure

```
AMS/
│
├── app.py                          # Main Flask application (all routes and logic)
├── template.html                   # GNITS-format HTML template for PDF shortage letters
│
├── templates/
│   ├── login.html                  # Faculty login page
│   └── index.html                  # Main dashboard (Upload, Analytics, SMS, Downloads, Admin)
│
├── static/
│   └── style.css                   # Stylesheet for the dashboard UI
│
├── database/
│   ├── create_students_db.py       # Run once: creates students table in students.db
│   ├── insert_students_db.py       # Run to insert student roll numbers and parent phones
│   └── view_students_db.py         # Run to verify records in students.db
│
├── students.db                     # SQLite: parent phone number lookup by Roll No.
├── ams.db                          # Auto-created: faculty accounts, upload history,
│                                   #   at-risk snapshots, SMS logs, download history
│
├── uploads/                        # Auto-created: stores uploaded .xlsx files
│                                   #   named as faculty_{id}_{original_filename}.xlsx
│
└── outputs/                        # Auto-created: stores generated report files
    ├── faculty_{id}_below75.xlsx   # Per-faculty filtered Excel report
    └── faculty_{id}_shortage.pdf  # Per-faculty PDF shortage letters
```

---

## Installation

**Prerequisites:** Python 3.9+, Windows / Linux / macOS

### Step 1 — Clone the repository

```bash
git clone https://github.com/rushmitha29/Automated_Student_Shortage_System.git
cd attendance-monitoring-system
```

### Step 2 — (Optional) Create and activate a virtual environment

```bash
python -m venv venv
source env/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
```

### Step 3 — Install Python dependencies

```bash
pip install flask pandas openpyxl pdfkit twilio werkzeug
```

### Step 4 — Install wkhtmltopdf (required for PDF generation)

Download and install from: https://wkhtmltopdf.org/downloads.html

Then update the executable path in `app.py`:

```python
# Windows (default)
wkhtml_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

# Linux / macOS
wkhtml_path = "/usr/local/bin/wkhtmltopdf"
```

---

## Database Setup

### Step 1 — Create `students.db`

```bash
python database/create_students_db.py
```

Creates the `students` table with `roll` (TEXT) and `parent_phone` (TEXT) columns.

### Step 2 — Insert student records

```bash
python database/insert_students_db.py
```

Populate with student roll numbers and 10-digit Indian parent mobile numbers (without the `+91` prefix — the system adds it automatically).

### Step 3 — Verify records (optional)

```bash
python database/view_students_db.py
```

> `ams.db` is created automatically on the first run of `app.py` via `init_db()`. No manual setup required.

---

## Running the Application

```bash
python app.py
```

Open your browser and navigate to:

```
http://127.0.0.1:5000
```

---

## Default Login Credentials

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin |
| `prof_sharma` | `faculty123` | Faculty |
| `prof_reddy` | `faculty123` | Faculty |
| `prof_krishna` | `faculty123` | Faculty |

> ⚠️ Update the default passwords before any institutional deployment.

---

## Excel File Format

The uploaded `.xlsx` file must contain the following columns:

| Column | Description |
|---|---|
| `S.No` | Serial number |
| `Roll No` | Unique student roll number (used for phone lookup) |
| `Name` | Full student name |
| `Present %` | Attendance percentage — accepts both decimal (0–1) and percentage (0–100) forms |
| Subject columns | Subject-wise attendance data (columns 4 onward, up to last 4 columns) |

Group rows in the Excel (rows where `Name` contains "Group") are used to determine the maximum classes held per subject for PDF generation.

---

## Requirements

```
flask
pandas
openpyxl
pdfkit
twilio
werkzeug
```

---

## Notes

- `students.db` must be created and populated before using the SMS feature. If a student's Roll No. is not found in `students.db`, no SMS is sent and the log entry shows `no_phone`.
- The `Present %` column is automatically normalised: values ≤ 1 are multiplied by 100 to convert from decimal to percentage form.
- PDF generation requires `template.html` to be present in the project root and `wkhtmltopdf` to be installed. If either is missing, only the Excel report is generated.
- All SQL queries use parameterised placeholders to prevent SQL injection.
- Flask sessions are signed with a server-side secret key. Change `app.secret_key` before production deployment.

---

