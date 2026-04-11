import os
import math
import json
import calendar
from datetime import datetime
from functools import wraps

import pandas as pd
import sqlite3
from flask import (Flask, render_template, request,
                   send_file, jsonify, session, redirect, url_for)
from werkzeug.security import generate_password_hash, check_password_hash
from twilio.rest import Client

app = Flask(__name__)
app.secret_key = "AMS_SECRET_KEY_CHANGE_IN_PROD_2025"   # change in production

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────────────────────────
#  DATABASE  (ams.db  —  faculty + per-faculty history)
# ─────────────────────────────────────────────────────────────────
DB = "ams.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Faculty accounts
    c.execute("""CREATE TABLE IF NOT EXISTS faculty (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT    UNIQUE NOT NULL,
        password TEXT    NOT NULL,
        name     TEXT    NOT NULL,
        dept     TEXT    NOT NULL DEFAULT '',
        role     TEXT    NOT NULL DEFAULT 'faculty',   -- 'admin' | 'faculty'
        created  TEXT    NOT NULL DEFAULT (datetime('now'))
    )""")

    # Upload history per faculty
    c.execute("""CREATE TABLE IF NOT EXISTS upload_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id  INTEGER NOT NULL,
        filename    TEXT,
        records     INTEGER DEFAULT 0,
        status      TEXT DEFAULT 'Processed',
        uploaded_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(faculty_id) REFERENCES faculty(id)
    )""")

    # Per-faculty at-risk snapshot (JSON blob)
    c.execute("""CREATE TABLE IF NOT EXISTS at_risk_data (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id  INTEGER NOT NULL UNIQUE,
        data_json   TEXT    DEFAULT '[]',
        updated_at  TEXT    DEFAULT (datetime('now')),
        FOREIGN KEY(faculty_id) REFERENCES faculty(id)
    )""")

    # SMS delivery log per faculty
    c.execute("""CREATE TABLE IF NOT EXISTS sms_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id  INTEGER NOT NULL,
        roll        TEXT,
        name        TEXT,
        percentage  TEXT,
        status      TEXT DEFAULT 'Sent',
        sent_at     TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(faculty_id) REFERENCES faculty(id)
    )""")

    # Download history per faculty
    c.execute("""CREATE TABLE IF NOT EXISTS download_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id  INTEGER NOT NULL,
        filename    TEXT,
        format      TEXT,
        downloaded_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(faculty_id) REFERENCES faculty(id)
    )""")

    # Seed: default admin (username: admin, password: admin123)
    c.execute("SELECT id FROM faculty WHERE username='admin'")
    if not c.fetchone():
        c.execute("""INSERT INTO faculty(username,password,name,dept,role)
                     VALUES(?,?,?,?,?)""",
                  ("admin",
                   generate_password_hash("admin123"),
                   "Administrator", "Administration", "admin"))

    # Seed: demo faculty accounts
    demo = [
        ("prof_sharma",  "faculty123", "Prof. Sharma",  "CSE",     "faculty"),
        ("prof_reddy",   "faculty123", "Prof. Reddy",   "ECE",     "faculty"),
        ("prof_krishna", "faculty123", "Prof. Krishna", "MECH",    "faculty"),
    ]
    for uname, pwd, name, dept, role in demo:
        c.execute("SELECT id FROM faculty WHERE username=?", (uname,))
        if not c.fetchone():
            c.execute("""INSERT INTO faculty(username,password,name,dept,role)
                         VALUES(?,?,?,?,?)""",
                      (uname, generate_password_hash(pwd), name, dept, role))

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────
#  HELPERS — parent phone lookup (students.db, separate file)
# ─────────────────────────────────────────────────────────────────
def get_parent_phone(roll):
    try:
        conn = sqlite3.connect("students.db")
        cur  = conn.cursor()
        cur.execute("SELECT parent_phone FROM students WHERE roll=?", (roll,))
        row  = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print("DB Error:", e)
        return None


# ─────────────────────────────────────────────────────────────────
#  TWILIO
# ─────────────────────────────────────────────────────────────────
ACCOUNT_SID   = os.getenv("TWILIO_SID")
AUTH_TOKEN    =os.getenv("TWILIO_TOKEN")
TWILIO_NUMBER = "Number"

def send_sms(phone, name, percent, roll):
    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        # ── NEW: include the student's actual attendance percentage ──
        try:
            pct_str = f"{float(percent):.2f}%"
        except Exception:
            pct_str = f"{percent}%"
        client.messages.create(
            body=(f"GNITS: Dear Parent, This is to inform you that your ward, "
                  f"{name} (Roll No: {roll}), has an attendance of {pct_str} which is "
                  f"below 75% this month. Kindly ensure regular attendance. "
                  f"Regards, HOD CSE GNITS"),
            from_=TWILIO_NUMBER,
            to=f"+91{phone}",
        )
        print(f"SMS → +91{phone} ({name})")
        return True
    except Exception as e:
        print("SMS Error:", e)
        return False


# ─────────────────────────────────────────────────────────────────
#  JSON-safe sanitize
# ─────────────────────────────────────────────────────────────────
def sanitize(data):
    clean = []
    for row in data:
        r = {}
        for k, v in row.items():
            k = str(k)
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
            elif hasattr(v, "item"):
                r[k] = v.item()
            else:
                r[k] = v
        clean.append(r)
    return clean


# ─────────────────────────────────────────────────────────────────
#  LOGIN REQUIRED DECORATOR
# ─────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "faculty_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Admin only"}), 403
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────
#  AUTH ROUTES
# ─────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "faculty_id" in session:
            return redirect(url_for("index"))
        return render_template("login.html")

    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    conn = get_db()
    row  = conn.execute("SELECT * FROM faculty WHERE username=?", (username,)).fetchone()
    conn.close()

    if not row or not check_password_hash(row["password"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["faculty_id"] = row["id"]
    session["username"]   = row["username"]
    session["name"]       = row["name"]
    session["dept"]       = row["dept"]
    session["role"]       = row["role"]

    return jsonify({"success": True, "name": row["name"], "role": row["role"]})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/me")
@login_required
def me():
    return jsonify({
        "id":       session["faculty_id"],
        "username": session["username"],
        "name":     session["name"],
        "dept":     session["dept"],
        "role":     session["role"],
    })


# ─────────────────────────────────────────────────────────────────
#  MAIN APP PAGE
# ─────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template("index.html")


# ─────────────────────────────────────────────────────────────────
#  UPLOAD
# ─────────────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    fid  = session["faculty_id"]
    file = request.files.get("file")

    if not file or file.filename == "":
        return jsonify({"error": "No file provided"}), 400

    filepath = os.path.join(UPLOAD_FOLDER, f"{fid}_{file.filename}")
    file.save(filepath)

    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        return jsonify({"error": f"Cannot read file: {e}"}), 400

    # ── NEW: read attendance range from form; default = below 75 ──
    att_range = request.form.get("att_range", "0-75")
    try:
        rng_low, rng_high = [float(x) for x in att_range.split("-")]
    except Exception:
        rng_low, rng_high = 0.0, 75.0

    if "Present %" in df.columns:
        df["Present %"] = df["Present %"].astype(str).str.replace("%", "").str.strip()
        df["Present %"] = pd.to_numeric(df["Present %"], errors="coerce")
        df["Present %"] = df["Present %"].apply(
            lambda x: x * 100 if pd.notnull(x) and x <= 1 else x)
        # ── NEW: filter by selected range instead of hard-coded < 75 ──
        filtered_df = df[
            (df["Present %"] >= rng_low) & (df["Present %"] < rng_high)
        ].copy()
    else:
        filtered_df = pd.DataFrame()

    total      = len(filtered_df)
    clean_data = sanitize(filtered_df.to_dict(orient="records"))

    # Save per-faculty Excel output
    out_excel = os.path.join(OUTPUT_FOLDER, f"faculty_{fid}_below75.xlsx")
    filtered_df.to_excel(out_excel, index=False)

    # Store at-risk data in DB
    conn = get_db()
    conn.execute("""INSERT INTO at_risk_data(faculty_id, data_json, updated_at)
                    VALUES(?,?,datetime('now'))
                    ON CONFLICT(faculty_id) DO UPDATE
                    SET data_json=excluded.data_json, updated_at=excluded.updated_at""",
                 (fid, json.dumps(clean_data)))

    # Store upload history
    conn.execute("""INSERT INTO upload_history(faculty_id,filename,records,status)
                    VALUES(?,?,?,?)""",
                 (fid, file.filename, total, "Processed"))
    conn.commit()
    conn.close()

    # PDF generation
    pdf_ready = False
    try:
        import pdfkit
        wkhtml = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
        if not os.path.exists(wkhtml):
            raise FileNotFoundError("wkhtmltopdf not found")

        cfg  = pdfkit.configuration(wkhtmltopdf=wkhtml)
        opts = {"enable-local-file-access": None, "page-size": "A4"}

        from_date_in = request.form.get("from_date")
        to_date_in   = request.form.get("to_date")
        today        = datetime.today()
        if from_date_in and to_date_in:
            from_date = datetime.strptime(from_date_in, "%Y-%m-%d").strftime("%d-%m-%Y")
            to_date   = datetime.strptime(to_date_in,   "%Y-%m-%d").strftime("%d-%m-%Y")
        else:
            m, y      = today.month, today.year
            from_date = f"01-{m:02d}-{y}"
            to_date   = f"{calendar.monthrange(y, m)[1]:02d}-{m:02d}-{y}"

        subject_cols = list(df.columns[3:-4]) if len(df.columns) > 7 else []
        pages = []

        for _, row in filtered_df.iterrows():
            if not os.path.exists("template.html"):
                break
            with open("template.html", encoding="utf-8") as fh:
                html = fh.read()

            subj_html = held_html = att_html = ""
            idx_list  = df.index[df["Roll No"] == row["Roll No"]].tolist()
            if not idx_list:
                continue
            held_row = None
            for i in range(idx_list[0], -1, -1):
                if "Group" in str(df.iloc[i].get("Name", "")):
                    held_row = df.iloc[i]; break

            for col in subject_cols:
                subj_html += f"<th>{str(col).replace(chr(10),' ')}</th>"
            if held_row is not None:
                for v in held_row[3:-4]:
                    held_html += f"<td>{int(v) if pd.notnull(v) else ''}</td>"
            for col in subject_cols:
                v = row.get(col)
                att_html += f"<td>{int(v) if pd.notnull(v) else ''}</td>"

            pct = row.get("Present %", "")
            try:   pct = f"{float(pct):.2f}"
            except Exception: pass

            sno = row.get("S.No", "")
            try:
                if pd.notnull(sno): sno = int(sno)
            except Exception: pass

            html = (html
                .replace("{{today_date}}", today.strftime("%d-%m-%Y"))
                .replace("{{from_date}}",  from_date)
                .replace("{{to_date}}",    to_date)
                .replace("{{name}}",       str(row.get("Name", "")))
                .replace("{{roll}}",       str(row.get("Roll No", "")))
                .replace("{{percentage}}", str(pct))
                .replace("{{subjects}}",   subj_html)
                .replace("{{held}}",       held_html)
                .replace("{{attended}}",   att_html)
                .replace("{{sno}}",        str(sno)))
            html += '<div style="page-break-after:always;"></div>'
            pages.append(html)

        if pages:
            out_pdf = os.path.join(OUTPUT_FOLDER, f"faculty_{fid}_shortage.pdf")
            pdfkit.from_string("".join(pages), out_pdf, configuration=cfg, options=opts)
            pdf_ready = True

    except Exception as e:
        print("PDF Error:", e)

    return jsonify({
        "success": True, "total": total, "data": clean_data,
        "download_ready": True, "pdf_ready": pdf_ready,
        "filename": file.filename,
        # ── NEW: return range info so frontend can display it ──
        "att_range": att_range,
        "range_low": rng_low,
        "range_high": rng_high,
    })


# ─────────────────────────────────────────────────────────────────
#  LOAD SAVED DATA (called when faculty logs in / page loads)
# ─────────────────────────────────────────────────────────────────
@app.route("/my_data")
@login_required
def my_data():
    fid  = session["faculty_id"]
    conn = get_db()

    # At-risk data
    row = conn.execute(
        "SELECT data_json, updated_at FROM at_risk_data WHERE faculty_id=?", (fid,)
    ).fetchone()
    at_risk    = json.loads(row["data_json"]) if row else []
    updated_at = row["updated_at"] if row else None

    # Upload history (latest 20)
    uploads = [dict(r) for r in conn.execute(
        "SELECT filename,records,status,uploaded_at FROM upload_history "
        "WHERE faculty_id=? ORDER BY id DESC LIMIT 20", (fid,)
    ).fetchall()]

    # SMS log (latest 50)
    sms = [dict(r) for r in conn.execute(
        "SELECT roll,name,percentage,status,sent_at FROM sms_log "
        "WHERE faculty_id=? ORDER BY id DESC LIMIT 50", (fid,)
    ).fetchall()]

    # Download history (latest 20)
    downloads = [dict(r) for r in conn.execute(
        "SELECT filename,format,downloaded_at FROM download_history "
        "WHERE faculty_id=? ORDER BY id DESC LIMIT 20", (fid,)
    ).fetchall()]

    # Sent students set
    sent_rolls = [r["roll"] for r in sms if r["status"] == "Sent"]

    conn.close()

    excel_exists = os.path.exists(os.path.join(OUTPUT_FOLDER, f"faculty_{fid}_below75.xlsx"))
    pdf_exists   = os.path.exists(os.path.join(OUTPUT_FOLDER, f"faculty_{fid}_shortage.pdf"))

    return jsonify({
        "at_risk":        at_risk,
        "updated_at":     updated_at,
        "uploads":        uploads,
        "sms_log":        sms,
        "downloads":      downloads,
        "sent_rolls":     sent_rolls,
        "download_ready": excel_exists,
        "pdf_ready":      pdf_exists,
    })


# ─────────────────────────────────────────────────────────────────
#  UPLOAD HISTORY
# ─────────────────────────────────────────────────────────────────
@app.route("/upload_history")
@login_required
def upload_history():
    fid  = session["faculty_id"]
    conn = get_db()
    rows = conn.execute(
        "SELECT filename,records,status,uploaded_at FROM upload_history "
        "WHERE faculty_id=? ORDER BY id DESC LIMIT 20", (fid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────────────────────────
#  SMS
# ─────────────────────────────────────────────────────────────────
@app.route("/send_all")
@login_required
def send_all():
    fid  = session["faculty_id"]
    conn = get_db()

    row  = conn.execute(
        "SELECT data_json FROM at_risk_data WHERE faculty_id=?", (fid,)
    ).fetchone()
    data = json.loads(row["data_json"]) if row else []

    # Rolls already sent
    sent_rows  = conn.execute(
        "SELECT roll FROM sms_log WHERE faculty_id=? AND status='Sent'", (fid,)
    ).fetchall()
    already    = {r["roll"] for r in sent_rows}

    results = []
    for student in data:
        roll  = str(student.get("Roll No", ""))
        name  = student.get("Name", "")
        pct   = student.get("Present %", "")
        phone = get_parent_phone(roll)

        if phone and roll not in already:
            ok = send_sms(phone, name, pct, roll)
            status = "Sent" if ok else "Failed"
            conn.execute(
                "INSERT INTO sms_log(faculty_id,roll,name,percentage,status) VALUES(?,?,?,?,?)",
                (fid, roll, name, str(pct), status)
            )
            already.add(roll)
            results.append({"roll": roll, "name": name, "status": status.lower()})
        elif roll in already:
            results.append({"roll": roll, "name": name, "status": "already_sent"})
        else:
            results.append({"roll": roll, "name": name, "status": "no_phone"})

    conn.commit()
    conn.close()
    sent_count = sum(1 for r in results if r["status"] == "sent")
    return jsonify({"success": True, "sent_count": sent_count, "results": results})


@app.route("/send_sms/<roll>")
@login_required
def send_single_sms(roll):
    fid  = session["faculty_id"]
    conn = get_db()

    row  = conn.execute(
        "SELECT data_json FROM at_risk_data WHERE faculty_id=?", (fid,)
    ).fetchone()
    data = json.loads(row["data_json"]) if row else []

    student = next((s for s in data if str(s.get("Roll No")) == str(roll)), None)
    if not student:
        conn.close()
        return jsonify({"error": "Student not found"}), 404

    # Check if already sent
    existing = conn.execute(
        "SELECT id FROM sms_log WHERE faculty_id=? AND roll=? AND status='Sent'",
        (fid, roll)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "SMS already sent"}), 400

    phone = get_parent_phone(roll)
    if not phone:
        conn.close()
        return jsonify({"error": "No phone number on record"}), 404

    ok = send_sms(phone, student.get("Name"), student.get("Present %"), roll)
    status = "Sent" if ok else "Failed"
    conn.execute(
        "INSERT INTO sms_log(faculty_id,roll,name,percentage,status) VALUES(?,?,?,?,?)",
        (fid, roll, student.get("Name"), str(student.get("Present %","")), status)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "roll": roll, "name": student.get("Name"), "status": status})


# ─────────────────────────────────────────────────────────────────
#  DOWNLOADS
# ─────────────────────────────────────────────────────────────────
@app.route("/download")
@login_required
def download():
    fid  = session["faculty_id"]
    path = os.path.join(OUTPUT_FOLDER, f"faculty_{fid}_below75.xlsx")
    if not os.path.exists(path):
        return jsonify({"error": "No file available"}), 404

    # Log download
    conn = get_db()
    conn.execute(
        "INSERT INTO download_history(faculty_id,filename,format) VALUES(?,?,?)",
        (fid, f"students_below_75_{session['username']}.xlsx", "XLSX")
    )
    conn.commit(); conn.close()
    return send_file(path, as_attachment=True,
                     download_name=f"students_below_75_{session['username']}.xlsx")


@app.route("/download_pdf")
@login_required
def download_pdf():
    fid  = session["faculty_id"]
    path = os.path.join(OUTPUT_FOLDER, f"faculty_{fid}_shortage.pdf")
    if not os.path.exists(path):
        return jsonify({"error": "No PDF available"}), 404

    conn = get_db()
    conn.execute(
        "INSERT INTO download_history(faculty_id,filename,format) VALUES(?,?,?)",
        (fid, f"shortage_{session['username']}.pdf", "PDF")
    )
    conn.commit(); conn.close()
    return send_file(path, as_attachment=True,
                     download_name=f"shortage_{session['username']}.pdf")


# ─────────────────────────────────────────────────────────────────
#  ADMIN — FACULTY MANAGEMENT
# ─────────────────────────────────────────────────────────────────
@app.route("/admin/faculty", methods=["GET"])
@login_required
@admin_required
def list_faculty():
    conn = get_db()
    rows = conn.execute(
        "SELECT id,username,name,dept,role,created FROM faculty ORDER BY id"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/admin/faculty", methods=["POST"])
@login_required
@admin_required
def add_faculty():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    name     = data.get("name", "").strip()
    dept     = data.get("dept", "").strip()
    role     = data.get("role", "faculty")

    if not username or not password or not name:
        return jsonify({"error": "username, password and name are required"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO faculty(username,password,name,dept,role) VALUES(?,?,?,?,?)",
            (username, generate_password_hash(password), name, dept, role)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Username already exists"}), 400
    conn.close()
    return jsonify({"success": True})


@app.route("/admin/faculty/<int:fid>", methods=["DELETE"])
@login_required
@admin_required
def delete_faculty(fid):
    if fid == session["faculty_id"]:
        return jsonify({"error": "Cannot delete yourself"}), 400
    conn = get_db()
    conn.execute("DELETE FROM faculty WHERE id=?", (fid,))
    conn.commit(); conn.close()
    return jsonify({"success": True})


@app.route("/admin/faculty/<int:fid>/reset_password", methods=["POST"])
@login_required
@admin_required
def reset_password(fid):
    data     = request.get_json() or {}
    new_pwd  = data.get("password", "").strip()
    if not new_pwd:
        return jsonify({"error": "Password required"}), 400
    conn = get_db()
    conn.execute("UPDATE faculty SET password=? WHERE id=?",
                 (generate_password_hash(new_pwd), fid))
    conn.commit(); conn.close()
    return jsonify({"success": True})


# ─────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    app.run(debug=True)