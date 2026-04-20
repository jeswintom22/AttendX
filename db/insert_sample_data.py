import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_utils import execute_write
from repositories import ensure_schema


def _required_id(row, label):
    if not row:
        raise RuntimeError(f"Missing sample {label}.")
    return row[0]


def insert_sample_data():
    def operation(conn):
        conn.execute(
            """
            INSERT OR IGNORE INTO Student (roll_no, name, department, semester)
            VALUES ('R001', 'Alice Johnson', 'Computer Science', '5')
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO Student (roll_no, name, department, semester)
            VALUES ('R002', 'Bob Smith', 'Mathematics', '5')
            """
        )

        conn.execute(
            "INSERT OR IGNORE INTO Subject (subject_name, total_classes) VALUES ('Mathematics', 10)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO Subject (subject_name, total_classes) VALUES ('Science', 8)"
        )

        alice_id = _required_id(
            conn.execute(
                "SELECT student_id FROM Student WHERE roll_no = ?",
                ("R001",),
            ).fetchone(),
            "student R001",
        )
        bob_id = _required_id(
            conn.execute(
                "SELECT student_id FROM Student WHERE roll_no = ?",
                ("R002",),
            ).fetchone(),
            "student R002",
        )
        math_id = _required_id(
            conn.execute(
                """
                SELECT subject_id
                FROM Subject
                WHERE LOWER(TRIM(subject_name)) = LOWER(TRIM(?))
                """,
                ("Mathematics",),
            ).fetchone(),
            "subject Mathematics",
        )

        attendance_rows = [
            (alice_id, math_id, "2023-10-01", 1, 1),
            (alice_id, math_id, "2023-10-02", 1, 1),
            (alice_id, math_id, "2023-10-03", 1, 0),
            (alice_id, math_id, "2023-10-04", 1, 1),
            (alice_id, math_id, "2023-10-05", 1, 1),
            (alice_id, math_id, "2023-10-06", 1, 1),
            (alice_id, math_id, "2023-10-07", 1, 1),
            (alice_id, math_id, "2023-10-08", 1, 1),
            (bob_id, math_id, "2023-10-01", 1, 1),
            (bob_id, math_id, "2023-10-02", 1, 0),
            (bob_id, math_id, "2023-10-03", 1, 0),
            (bob_id, math_id, "2023-10-04", 1, 1),
            (bob_id, math_id, "2023-10-05", 1, 1),
            (bob_id, math_id, "2023-10-06", 1, 1),
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO Attendance
            (student_id, subject_id, date, scan_no, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            attendance_rows,
        )

    ensure_schema()
    execute_write(operation)


if __name__ == "__main__":
    insert_sample_data()
    print("Sample data inserted.")
