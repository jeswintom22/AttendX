import logging
import sqlite3
from datetime import date, timedelta

from app_errors import ConflictError, NotFoundError, ValidationError
from db_utils import execute_write, read_connection

logger = logging.getLogger("attendx.repositories")


def _dict(row):
    return dict(row) if row is not None else None


def _scalar(row, default=0):
    return row[0] if row is not None and row[0] is not None else default


def _row_ids(rows, key):
    return {row[key] for row in rows}


def _deduplicate_subjects(conn):
    duplicate_groups = conn.execute(
        """
        SELECT LOWER(TRIM(subject_name)) AS normalized_name,
               MIN(subject_id) AS keep_id,
               GROUP_CONCAT(subject_id) AS subject_ids
        FROM Subject
        GROUP BY LOWER(TRIM(subject_name))
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    for group in duplicate_groups:
        keep_id = group["keep_id"]
        subject_ids = [int(value) for value in group["subject_ids"].split(",")]
        duplicate_ids = [subject_id for subject_id in subject_ids if subject_id != keep_id]
        if not duplicate_ids:
            continue
        placeholders = ",".join("?" for _ in duplicate_ids)
        logger.warning(
            "Deduplicating subject ids %s into subject_id=%s",
            duplicate_ids,
            keep_id,
        )
        conn.execute(
            f"UPDATE Attendance SET subject_id = ? WHERE subject_id IN ({placeholders})",
            (keep_id, *duplicate_ids),
        )
        conn.execute(
            f"UPDATE ClassSchedule SET subject_id = ? WHERE subject_id IN ({placeholders})",
            (keep_id, *duplicate_ids),
        )
        conn.execute(
            f"DELETE FROM Subject WHERE subject_id IN ({placeholders})",
            duplicate_ids,
        )


def _deduplicate_attendance_schedule(conn):
    conn.execute(
        """
        DELETE FROM Attendance
        WHERE schedule_id IS NOT NULL
          AND attendance_id NOT IN (
              SELECT MIN(attendance_id)
              FROM Attendance
              WHERE schedule_id IS NOT NULL
              GROUP BY student_id, schedule_id, date
          )
        """
    )


def ensure_schema():
    def operation(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Student (
                student_id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_no TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                department TEXT,
                semester TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Subject (
                subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_name TEXT NOT NULL,
                total_classes INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS StudentFace (
                student_id INTEGER PRIMARY KEY,
                encoding BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Attendance (
                attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                scan_no INTEGER NOT NULL CHECK (scan_no BETWEEN 1 AND 4),
                status INTEGER NOT NULL CHECK (status IN (0, 1)),
                schedule_id INTEGER,
                FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE,
                FOREIGN KEY (subject_id) REFERENCES Subject(subject_id),
                FOREIGN KEY (schedule_id) REFERENCES ClassSchedule(schedule_id),
                UNIQUE(student_id, subject_id, date, scan_no)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ClassSchedule (
                schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                is_free_period INTEGER NOT NULL CHECK (is_free_period IN (0,1)),
                FOREIGN KEY (subject_id) REFERENCES Subject(subject_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Message (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        attendance_columns = [
            row["name"] for row in conn.execute("PRAGMA table_info(Attendance)").fetchall()
        ]
        if "schedule_id" not in attendance_columns:
            conn.execute("ALTER TABLE Attendance ADD COLUMN schedule_id INTEGER")

        student_columns = [
            row["name"] for row in conn.execute("PRAGMA table_info(Student)").fetchall()
        ]
        if "semester" not in student_columns:
            conn.execute("ALTER TABLE Student ADD COLUMN semester TEXT")

        _deduplicate_subjects(conn)
        _deduplicate_attendance_schedule(conn)

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_subject_name_normalized
            ON Subject(LOWER(TRIM(subject_name)))
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_student_roll_no ON Student(roll_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_student_face_student_id ON StudentFace(student_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_day_start ON ClassSchedule(day, start_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_student_subject_date ON Attendance(student_id, subject_id, date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_schedule_date ON Attendance(schedule_id, date)")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_schedule
            ON Attendance(student_id, schedule_id, date)
            WHERE schedule_id IS NOT NULL
            """
        )

    execute_write(operation)
    logger.info("Database schema is ready")


def list_students():
    with read_connection() as conn:
        return conn.execute(
            "SELECT student_id, roll_no, name, department, semester FROM Student ORDER BY roll_no"
        ).fetchall()


def create_student(student):
    def operation(conn):
        cursor = conn.execute(
            """
            INSERT INTO Student (roll_no, name, department, semester)
            VALUES (?, ?, ?, ?)
            """,
            (
                student["roll_no"],
                student["name"],
                student["department"],
                student["semester"],
            ),
        )
        logger.info("Student created roll_no=%s", student["roll_no"])
        return cursor.lastrowid

    try:
        student_id = execute_write(operation)
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Roll number already exists.") from exc

    return {
        "student_id": student_id,
        "roll_no": student["roll_no"],
        "name": student["name"],
        "department": student["department"],
        "semester": student["semester"],
    }


def get_student(student_id):
    with read_connection() as conn:
        row = conn.execute(
            "SELECT student_id, roll_no, name, department, semester FROM Student WHERE student_id = ?",
            (student_id,),
        ).fetchone()
    if not row:
        raise NotFoundError("Student not found.")
    return row


def _get_or_create_subject(conn, subject_name):
    row = conn.execute(
        """
        SELECT subject_id, subject_name
        FROM Subject
        WHERE LOWER(TRIM(subject_name)) = LOWER(TRIM(?))
        """,
        (subject_name,),
    ).fetchone()
    if row:
        return row["subject_id"]

    try:
        conn.execute(
            "INSERT INTO Subject (subject_name, total_classes) VALUES (?, 0)",
            (subject_name,),
        )
    except sqlite3.IntegrityError:
        logger.info("Subject inserted concurrently; selecting existing subject=%s", subject_name)

    row = conn.execute(
        """
        SELECT subject_id, subject_name
        FROM Subject
        WHERE LOWER(TRIM(subject_name)) = LOWER(TRIM(?))
        """,
        (subject_name,),
    ).fetchone()
    if not row:
        raise NotFoundError(f"Subject not found: {subject_name}")
    return row["subject_id"]


def create_schedule(schedule):
    def operation(conn):
        subject_id = _get_or_create_subject(conn, schedule["subject_name"])
        cursor = conn.execute(
            """
            INSERT INTO ClassSchedule
            (subject_id, day, start_time, end_time, is_free_period)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                subject_id,
                schedule["day"],
                schedule["start_time"],
                schedule["end_time"],
                schedule["is_free_period"],
            ),
        )
        logger.info(
            "Schedule created subject=%s day=%s start=%s",
            schedule["subject_name"],
            schedule["day"],
            schedule["start_time"],
        )
        return cursor.lastrowid, subject_id

    schedule_id, subject_id = execute_write(operation)
    return {
        "schedule_id": schedule_id,
        "subject_id": subject_id,
        "subject_name": schedule["subject_name"],
        "day": schedule["day"],
        "start_time": schedule["start_time"],
        "end_time": schedule["end_time"],
        "is_free_period": bool(schedule["is_free_period"]),
    }


def list_schedules(day):
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                cs.schedule_id,
                cs.subject_id,
                s.subject_name,
                cs.start_time,
                cs.end_time,
                cs.is_free_period
            FROM ClassSchedule cs
            JOIN Subject s ON cs.subject_id = s.subject_id
            WHERE cs.day = ?
            ORDER BY cs.start_time
            """,
            (day,),
        ).fetchall()

    return [
        {
            "id": row["schedule_id"],
            "schedule_id": row["schedule_id"],
            "subject_id": row["subject_id"],
            "subject_name": row["subject_name"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "free_period": bool(row["is_free_period"]),
            "is_free_period": bool(row["is_free_period"]),
        }
        for row in rows
    ]


def get_schedule(schedule_id):
    with read_connection() as conn:
        row = conn.execute(
            """
            SELECT cs.schedule_id, cs.subject_id, cs.day, cs.start_time, cs.end_time,
                   cs.is_free_period, s.subject_name
            FROM ClassSchedule cs
            JOIN Subject s ON s.subject_id = cs.subject_id
            WHERE cs.schedule_id = ?
            """,
            (schedule_id,),
        ).fetchone()
    if not row:
        raise NotFoundError("Schedule not found.")
    return row


def _compute_scan_no(conn, schedule_id, day):
    rows = conn.execute(
        "SELECT schedule_id FROM ClassSchedule WHERE day = ? ORDER BY start_time",
        (day,),
    ).fetchall()
    schedule_ids = [row["schedule_id"] for row in rows]
    scan_no = schedule_ids.index(schedule_id) + 1 if schedule_id in schedule_ids else 1
    if scan_no > 4:
        logger.warning("Scan number capped at 4 for schedule_id=%s", schedule_id)
        scan_no = 4
    return scan_no


def record_attendance_for_schedule(schedule_id, student_ids):
    today = date.today().isoformat()

    def operation(conn):
        schedule = conn.execute(
            """
            SELECT schedule_id, subject_id, day, is_free_period
            FROM ClassSchedule
            WHERE schedule_id = ?
            """,
            (schedule_id,),
        ).fetchone()
        if not schedule:
            raise NotFoundError("Schedule not found.")
        if schedule["is_free_period"]:
            return {"inserted": [], "free_period": True}

        placeholders = ",".join("?" for _ in student_ids)
        student_rows = conn.execute(
            f"SELECT student_id FROM Student WHERE student_id IN ({placeholders})",
            student_ids,
        ).fetchall()
        existing_ids = _row_ids(student_rows, "student_id")
        missing_ids = [student_id for student_id in student_ids if student_id not in existing_ids]
        if missing_ids:
            raise NotFoundError(f"Student not found: {missing_ids[0]}")

        scan_no = _compute_scan_no(conn, schedule_id, schedule["day"])
        inserted = []
        for student_id in student_ids:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO Attendance
                (student_id, subject_id, date, scan_no, status, schedule_id)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    student_id,
                    schedule["subject_id"],
                    today,
                    scan_no,
                    schedule_id,
                ),
            )
            if cursor.rowcount:
                inserted.append(student_id)

        logger.info(
            "Attendance recorded schedule_id=%s inserted=%s skipped=%s",
            schedule_id,
            len(inserted),
            len(student_ids) - len(inserted),
        )
        return {"inserted": inserted, "free_period": False}

    return execute_write(operation)


def mark_scan(roll_no, subject_name, scan_no, status):
    today = date.today().isoformat()

    if scan_no < 1 or scan_no > 4:
        raise ValidationError("Invalid scan number.")
    if status not in (0, 1):
        raise ValidationError("Invalid attendance status.")

    def operation(conn):
        student = conn.execute(
            "SELECT student_id FROM Student WHERE roll_no = ?",
            (roll_no,),
        ).fetchone()
        if not student:
            return False

        subject_id = _get_or_create_subject(conn, subject_name)
        conn.execute(
            """
            INSERT OR IGNORE INTO Attendance
            (student_id, subject_id, date, scan_no, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (student["student_id"], subject_id, today, scan_no, status),
        )
        return True

    return execute_write(operation)


def store_face_encoding(student_id, encoding_bytes):
    def operation(conn):
        student = conn.execute(
            "SELECT student_id FROM Student WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        if not student:
            raise NotFoundError("Student not found.")
        conn.execute(
            "INSERT OR REPLACE INTO StudentFace (student_id, encoding) VALUES (?, ?)",
            (student_id, sqlite3.Binary(encoding_bytes)),
        )
        logger.info("Face encoding stored student_id=%s", student_id)

    execute_write(operation)


def list_face_encodings():
    with read_connection() as conn:
        return conn.execute(
            """
            SELECT sf.student_id, s.roll_no, s.name, sf.encoding
            FROM StudentFace sf
            JOIN Student s ON s.student_id = sf.student_id
            ORDER BY s.roll_no
            """
        ).fetchall()


def create_message(content):
    def operation(conn):
        conn.execute("INSERT INTO Message (content) VALUES (?)", (content,))
        logger.info("Message created")

    execute_write(operation)


def get_latest_message():
    with read_connection() as conn:
        row = conn.execute(
            "SELECT content FROM Message ORDER BY created_at DESC, message_id DESC LIMIT 1"
        ).fetchone()
    return row["content"] if row else "No message"


def get_dashboard_data():
    today_name = date.today().strftime("%A")
    trend_dates = [date.today() - timedelta(days=offset) for offset in range(6, -1, -1)]
    start_date = (date.today() - timedelta(days=6)).isoformat()

    with read_connection() as conn:
        total_students = _scalar(conn.execute("SELECT COUNT(*) FROM Student").fetchone())
        active_classes = _scalar(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ClassSchedule
                WHERE day = ? AND is_free_period = 0
                """,
                (today_name,),
            ).fetchone()
        )
        running_now = _scalar(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ClassSchedule
                WHERE day = ?
                  AND is_free_period = 0
                  AND time(start_time) <= time('now','localtime')
                  AND time(end_time) >= time('now','localtime')
                """,
                (today_name,),
            ).fetchone()
        )
        upcoming_rows = conn.execute(
            """
            SELECT s.subject_name, cs.start_time, cs.end_time
            FROM ClassSchedule cs
            JOIN Subject s ON s.subject_id = cs.subject_id
            WHERE cs.day = ?
              AND cs.is_free_period = 0
              AND time(cs.start_time) >= time('now','localtime')
            ORDER BY time(cs.start_time) ASC
            LIMIT 2
            """,
            (today_name,),
        ).fetchall()

        trend_rows = conn.execute(
            """
            WITH daily AS (
                SELECT date, student_id, subject_id, SUM(status) AS total_present
                FROM Attendance
                WHERE date >= ?
                GROUP BY date, student_id, subject_id
            )
            SELECT date,
                   SUM(CASE WHEN total_present >= 3 THEN 1 ELSE 0 END) AS present_count,
                   COUNT(*) AS total_count
            FROM daily
            GROUP BY date
            """,
            (start_date,),
        ).fetchall()
        trend_by_date = {row["date"]: row for row in trend_rows}

        mix_row = conn.execute(
            """
            WITH daily AS (
                SELECT student_id, subject_id, date, SUM(status) AS total_present
                FROM Attendance
                WHERE date >= ?
                GROUP BY student_id, subject_id, date
            )
            SELECT
                SUM(CASE WHEN total_present >= 3 THEN 1 ELSE 0 END) AS present_count,
                SUM(CASE WHEN total_present BETWEEN 1 AND 2 THEN 1 ELSE 0 END) AS late_count,
                SUM(CASE WHEN total_present = 0 THEN 1 ELSE 0 END) AS absent_count,
                COUNT(*) AS total_count
            FROM daily
            """,
            (start_date,),
        ).fetchone()

    attendance_trend = []
    for trend_date in trend_dates:
        date_str = trend_date.isoformat()
        row = trend_by_date.get(date_str)
        present_count = row["present_count"] if row and row["present_count"] else 0
        total_count = row["total_count"] if row and row["total_count"] else 0
        attendance_trend.append(
            {
                "label": trend_date.strftime("%a"),
                "value": round((present_count / total_count) * 100) if total_count else 0,
                "muted": total_count == 0,
            }
        )

    return {
        "total_students": total_students,
        "active_classes": active_classes,
        "running_now": running_now,
        "upcoming_classes": [
            {
                "subject": row["subject_name"],
                "time": f"{row['start_time']} - {row['end_time']}",
            }
            for row in upcoming_rows
        ],
        "attendance_trend": attendance_trend,
        "mix": _dict(mix_row),
    }


def get_attendance_summary_rows():
    with read_connection() as conn:
        return conn.execute(
            """
            WITH daily AS (
                SELECT student_id, subject_id, date, SUM(status) AS present_count
                FROM Attendance
                GROUP BY student_id, subject_id, date
            )
            SELECT
                s.roll_no,
                sub.subject_name,
                COUNT(*) AS total_classes,
                SUM(CASE WHEN daily.present_count >= 3 THEN 1 ELSE 0 END) AS present_classes
            FROM daily
            JOIN Student s ON daily.student_id = s.student_id
            JOIN Subject sub ON daily.subject_id = sub.subject_id
            GROUP BY daily.student_id, daily.subject_id
            ORDER BY s.roll_no, sub.subject_name
            """
        ).fetchall()


def get_final_attendance_rows():
    with read_connection() as conn:
        return conn.execute(
            """
            SELECT
                s.roll_no,
                sub.subject_name,
                a.date,
                SUM(a.status) AS present_count
            FROM Attendance a
            JOIN Student s ON a.student_id = s.student_id
            JOIN Subject sub ON a.subject_id = sub.subject_id
            GROUP BY a.student_id, a.subject_id, a.date
            ORDER BY a.date DESC, s.roll_no, sub.subject_name
            """
        ).fetchall()


def get_export_rows():
    with read_connection() as conn:
        students = conn.execute(
            "SELECT student_id, roll_no, name, department, semester FROM Student ORDER BY roll_no"
        ).fetchall()
        subjects = conn.execute(
            "SELECT subject_id, subject_name FROM Subject ORDER BY subject_name"
        ).fetchall()
        daily = conn.execute(
            """
            SELECT student_id, subject_id, date, SUM(status) AS present_count
            FROM Attendance
            GROUP BY student_id, subject_id, date
            """
        ).fetchall()
    return students, subjects, daily
