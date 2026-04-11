import sqlite3

conn = sqlite3.connect("students.db")
cursor = conn.cursor()

students = [
    
]

cursor.executemany(
    "INSERT OR IGNORE INTO students (roll, name, parent_phone) VALUES (?, ?, ?)",
    students
)

conn.commit()
conn.close()

print("Students inserted successfully")