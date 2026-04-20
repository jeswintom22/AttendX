import importlib
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


MODULES_TO_RELOAD = [
    "app",
    "services",
    "repositories",
    "db_utils",
    "validators",
    "logic.export_excel",
]


class AttendXTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "attendance.db")
        os.environ["ATTENDX_DB_PATH"] = self.db_path
        os.environ["ATTENDX_SECRET_KEY"] = "test-secret"
        os.environ["ATTENDX_DB_BUSY_TIMEOUT_MS"] = "50"
        os.environ["ATTENDX_DB_WRITE_RETRIES"] = "5"
        os.environ["ATTENDX_RECOGNITION_MIN_INTERVAL_SECONDS"] = "0"

        for module in MODULES_TO_RELOAD:
            sys.modules.pop(module, None)

        self.db_utils = importlib.import_module("db_utils")
        self.repositories = importlib.import_module("repositories")
        self.app_module = importlib.import_module("app")
        self.app = self.app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.client.post(
            "/api/login",
            json={"username": "admin", "password": "admin123"},
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_wal_mode_enabled(self):
        with self.db_utils.read_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_student_create_duplicate_and_validation(self):
        response = self.client.post(
            "/api/students",
            json={
                "roll_no": "CSE-001",
                "name": "Ada Lovelace",
                "department": "Computer Science",
                "semester": "5",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["student"]["roll_no"], "CSE-001")

        duplicate = self.client.post(
            "/api/students",
            json={
                "roll_no": "CSE-001",
                "name": "Ada",
                "department": "Computer Science",
                "semester": "5",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        invalid = self.client.post("/api/students", json={"roll_no": "", "name": ""})
        self.assertEqual(invalid.status_code, 400)

    def test_schedule_and_attendance_flow(self):
        student = self.client.post(
            "/api/students",
            json={
                "roll_no": "CSE-002",
                "name": "Grace Hopper",
                "department": "Computer Science",
                "semester": "5",
            },
        ).get_json()["student"]

        invalid_schedule = self.client.post(
            "/api/schedule",
            json={
                "subject_name": "Algorithms",
                "day": "Monday",
                "start_time": "11:00",
                "end_time": "10:00",
                "is_free_period": False,
            },
        )
        self.assertEqual(invalid_schedule.status_code, 400)

        schedule = self.client.post(
            "/api/schedule",
            json={
                "subject_name": "Algorithms",
                "day": "Monday",
                "start_time": "10:00",
                "end_time": "11:00",
                "is_free_period": False,
            },
        ).get_json()["schedule"]

        attendance = self.client.post(
            "/attendance",
            json={
                "schedule_id": schedule["schedule_id"],
                "student_ids": [student["student_id"]],
            },
        )
        self.assertEqual(attendance.status_code, 200)
        self.assertEqual(attendance.get_json()["inserted"], [student["student_id"]])

        duplicate = self.client.post(
            "/attendance",
            json={
                "schedule_id": schedule["schedule_id"],
                "student_ids": [student["student_id"]],
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.get_json()["inserted"], [])

    def test_face_register_and_recognition_with_mocked_engine(self):
        try:
            import numpy as np  # type: ignore
        except Exception as exc:
            self.skipTest(f"NumPy is not importable in this environment: {exc}")

        class FakeFaceRecognition:
            encoding = np.ones(128, dtype=np.float64)
            next_encodings = None

            @classmethod
            def load_image_file(cls, file_obj):
                return b"image"

            @classmethod
            def face_locations(cls, image):
                return [(0, 1, 1, 0)]

            @classmethod
            def face_encodings(cls, image, face_locations=None):
                if cls.next_encodings is not None:
                    encodings = cls.next_encodings
                    cls.next_encodings = None
                    return encodings
                return [cls.encoding]

            @classmethod
            def compare_faces(cls, known_encodings, encoding, tolerance=0.5):
                return [np.array_equal(known, encoding) for known in known_encodings]

        self.app_module.FACE_RECOGNITION_AVAILABLE = True
        self.app_module.face_recognition = FakeFaceRecognition

        student = self.client.post(
            "/api/students",
            json={
                "roll_no": "CSE-003",
                "name": "Katherine Johnson",
                "department": "Mathematics",
                "semester": "5",
            },
        ).get_json()["student"]
        schedule = self.client.post(
            "/api/schedule",
            json={
                "subject_name": "Numerical Methods",
                "day": "Monday",
                "start_time": "12:00",
                "end_time": "13:00",
                "is_free_period": False,
            },
        ).get_json()["schedule"]

        image = "data:image/jpeg;base64,AAAA"
        register = self.client.post(
            "/api/face-register/capture",
            json={"student_id": student["student_id"], "image": image},
        )
        self.assertEqual(register.status_code, 200)

        recognize = self.client.post(
            "/api/recognize",
            json={"schedule_id": schedule["schedule_id"], "image": image},
        )
        self.assertEqual(recognize.status_code, 200)
        self.assertEqual(recognize.get_json()["recognized"], ["Katherine Johnson"])

        FakeFaceRecognition.next_encodings = []
        no_face = self.client.post(
            "/api/recognize",
            json={"schedule_id": schedule["schedule_id"], "image": image},
        )
        self.assertEqual(no_face.status_code, 200)
        self.assertEqual(no_face.get_json()["message"], "No face detected.")

    def test_transaction_rollback_and_retry(self):
        def failing_operation(conn):
            conn.execute(
                "INSERT INTO Student (roll_no, name, department, semester) VALUES (?, ?, ?, ?)",
                ("ROLLBACK-1", "Rollback", "CS", "1"),
            )
            raise RuntimeError("force rollback")

        with self.assertRaises(RuntimeError):
            self.db_utils.execute_write(failing_operation)

        with self.db_utils.read_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM Student WHERE roll_no = ?",
                ("ROLLBACK-1",),
            ).fetchone()[0]
        self.assertEqual(count, 0)

        locker = sqlite3.connect(
            self.db_path,
            isolation_level=None,
            timeout=0.05,
            check_same_thread=False,
        )
        locker.execute("PRAGMA journal_mode = WAL")
        locker.execute("BEGIN IMMEDIATE")

        def release_lock():
            time.sleep(0.15)
            locker.rollback()
            locker.close()

        thread = threading.Thread(target=release_lock)
        thread.start()

        self.db_utils.execute_write(
            lambda conn: conn.execute(
                "INSERT INTO Student (roll_no, name, department, semester) VALUES (?, ?, ?, ?)",
                ("RETRY-1", "Retry", "CS", "1"),
            )
        )
        thread.join()

        with self.db_utils.read_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM Student WHERE roll_no = ?",
                ("RETRY-1",),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_subject_deduplication_migration(self):
        with self.db_utils.write_transaction() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_subject_name_normalized")
            conn.execute(
                "INSERT INTO Subject (subject_name, total_classes) VALUES (?, 0)",
                ("Math",),
            )
            conn.execute(
                "INSERT INTO Subject (subject_name, total_classes) VALUES (?, 0)",
                (" math ",),
            )

        self.repositories.ensure_schema()

        with self.db_utils.read_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM Subject WHERE LOWER(TRIM(subject_name)) = LOWER(TRIM(?))",
                ("math",),
            ).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
