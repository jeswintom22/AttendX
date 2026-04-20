from db_utils import read_connection


def _percentage(present, total):
    return round((present / total) * 100, 2) if total else 0


def subject_attendance(student_id, subject_id):
    with read_connection() as conn:
        row = conn.execute(
            """
            WITH daily AS (
                SELECT date, SUM(status) AS present_count
                FROM Attendance
                WHERE student_id = ? AND subject_id = ?
                GROUP BY date
            )
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN present_count >= 3 THEN 1 ELSE 0 END) AS present
            FROM daily
            """,
            (student_id, subject_id),
        ).fetchone()

    total = row["total"] if row and row["total"] else 0
    present = row["present"] if row and row["present"] else 0
    return _percentage(present, total)


def overall_attendance(student_id):
    with read_connection() as conn:
        row = conn.execute(
            """
            WITH daily AS (
                SELECT subject_id, date, SUM(status) AS present_count
                FROM Attendance
                WHERE student_id = ?
                GROUP BY subject_id, date
            )
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN present_count >= 3 THEN 1 ELSE 0 END) AS present
            FROM daily
            """,
            (student_id,),
        ).fetchone()

    total = row["total"] if row and row["total"] else 0
    present = row["present"] if row and row["present"] else 0
    return _percentage(present, total)
