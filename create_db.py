import sqlite3

conn = sqlite3.connect("students.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE students(
    roll TEXT PRIMARY KEY,
    name TEXT,
    parent_phone TEXT
)
""")

conn.commit()
conn.close()

print("Database created successfully")