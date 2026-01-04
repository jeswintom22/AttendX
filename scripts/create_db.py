import sqlite3

# Step 3: Create SQLite database file
# This connects to 'attendance.db' in the db folder. If the file doesn't exist, SQLite creates it.
conn = sqlite3.connect('db/attendance.db')
cursor = conn.cursor()

print("SQLite database file created at db/attendance.db")

# Step 4: Create Student table
cursor.execute('''
CREATE TABLE IF NOT EXISTS Student (
    student_id INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    department TEXT
)
''')
print("Student table created.")

# Step 5: Create Subject table
cursor.execute('''
CREATE TABLE IF NOT EXISTS Subject (
    subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_name TEXT NOT NULL,
    total_classes INTEGER NOT NULL
)
''')
print("Subject table created.")

# Step 6: Create Attendance table
cursor.execute('''
CREATE TABLE IF NOT EXISTS Attendance (
    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status INTEGER NOT NULL CHECK (status IN (0, 1)),
    FOREIGN KEY (student_id) REFERENCES Student(student_id),
    FOREIGN KEY (subject_id) REFERENCES Subject(subject_id),
    UNIQUE(student_id, subject_id, date)
)
''')
print("Attendance table created.")

# Commit and close
conn.commit()
conn.close()

print("Database setup complete.")