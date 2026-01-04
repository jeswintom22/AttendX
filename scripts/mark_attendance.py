import sqlite3

def mark_attendance(student_id, subject_id, date, status):
    """
    Marks attendance for a student in a subject on a specific date.
    status: 1 for Present, 0 for Absent
    Ensures one attendance per student per subject per day using UNIQUE constraint.
    """
    conn = sqlite3.connect('db/attendance.db')
    cursor = conn.cursor()

    try:
        # Insert attendance; UNIQUE constraint prevents duplicates
        cursor.execute('''
        INSERT OR IGNORE INTO Attendance (student_id, subject_id, date, status)
        VALUES (?, ?, ?, ?)
        ''', (student_id, subject_id, date, status))

        if cursor.rowcount > 0:
            status_text = "Present" if status == 1 else "Absent"
            print(f"Attendance marked: Student {student_id}, Subject {subject_id}, Date {date}, Status {status_text}")
        else:
            print(f"Attendance already exists for Student {student_id}, Subject {subject_id}, Date {date}")

        conn.commit()
    except sqlite3.Error as e:
        print(f"Error marking attendance: {e}")
    finally:
        conn.close()

# Example usage
if __name__ == "__main__":
    # Mark Alice present
    mark_attendance(1, 1, '2023-10-09', 1)
    # Try to mark again (should be ignored)
    mark_attendance(1, 1, '2023-10-09', 0)