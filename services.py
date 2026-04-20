import io
import logging
import os
import threading
import time

from app_errors import NotFoundError, ServiceUnavailableError, TooManyRequestsError, ValidationError
import repositories
from validators import decode_image_data_url

logger = logging.getLogger("attendx.services")

FACE_CACHE_TTL_SECONDS = int(os.getenv("ATTENDX_FACE_CACHE_TTL_SECONDS", "60"))
SCHEDULE_CACHE_TTL_SECONDS = int(os.getenv("ATTENDX_SCHEDULE_CACHE_TTL_SECONDS", "30"))
RECOGNITION_MIN_INTERVAL_SECONDS = float(os.getenv("ATTENDX_RECOGNITION_MIN_INTERVAL_SECONDS", "2.0"))
RECOGNITION_MAX_WORKERS = max(1, int(os.getenv("ATTENDX_RECOGNITION_MAX_WORKERS", "1")))

_face_cache = {"loaded_at": 0.0, "items": []}
_face_cache_lock = threading.RLock()
_schedule_cache = {}
_schedule_cache_lock = threading.RLock()
_recognition_semaphore = threading.BoundedSemaphore(RECOGNITION_MAX_WORKERS)
_recognition_rate_lock = threading.RLock()
_last_recognition_by_ip = {}
_numpy_module = None
_numpy_error = None


def list_students():
    return repositories.list_students()


def create_student(student):
    return repositories.create_student(student)


def fetch_schedule_for_day(day, *, force=False):
    now = time.time()
    with _schedule_cache_lock:
        cached = _schedule_cache.get(day)
        if (
            not force
            and cached
            and (now - cached["loaded_at"]) < SCHEDULE_CACHE_TTL_SECONDS
        ):
            return cached["items"]

    schedules = repositories.list_schedules(day)
    with _schedule_cache_lock:
        _schedule_cache[day] = {"loaded_at": now, "items": schedules}
    return schedules


def invalidate_schedule_cache(day=None):
    with _schedule_cache_lock:
        if day:
            _schedule_cache.pop(day, None)
        else:
            _schedule_cache.clear()


def create_schedule(schedule):
    created = repositories.create_schedule(schedule)
    invalidate_schedule_cache(schedule["day"])
    return created


def create_message(content):
    repositories.create_message(content)


def get_latest_message():
    return repositories.get_latest_message()


def record_attendance(schedule_id, student_ids):
    return repositories.record_attendance_for_schedule(schedule_id, student_ids)


def _get_numpy():
    global _numpy_module, _numpy_error
    if _numpy_module is not None:
        return _numpy_module
    if _numpy_error is not None:
        raise ServiceUnavailableError(
            "NumPy is not available. Reinstall NumPy to use face recognition."
        ) from _numpy_error

    try:
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        _numpy_error = exc
        logger.warning("NumPy import failed: %s", exc)
        raise ServiceUnavailableError(
            "NumPy is not available. Reinstall NumPy to use face recognition."
        ) from exc

    _numpy_module = np
    return np


def load_face_cache(force=False):
    now = time.time()
    with _face_cache_lock:
        if (
            not force
            and _face_cache["items"]
            and (now - _face_cache["loaded_at"]) < FACE_CACHE_TTL_SECONDS
        ):
            return list(_face_cache["items"])

    rows = repositories.list_face_encodings()
    np = _get_numpy()
    items = []
    for row in rows:
        if row["encoding"] is None:
            continue
        encoding = np.frombuffer(row["encoding"], dtype=np.float64)
        if encoding.shape[0] != 128:
            logger.warning("Invalid face encoding length for student_id=%s", row["student_id"])
            continue
        items.append(
            {
                "student_id": row["student_id"],
                "roll_no": row["roll_no"],
                "name": row["name"],
                "encoding": encoding,
            }
        )

    with _face_cache_lock:
        _face_cache["loaded_at"] = now
        _face_cache["items"] = items
    return list(items)


def invalidate_face_cache():
    with _face_cache_lock:
        _face_cache["loaded_at"] = 0.0
        _face_cache["items"] = []


def register_face(student_id, image_data_url, face_recognition_module):
    image_bytes = decode_image_data_url(image_data_url)
    image = face_recognition_module.load_image_file(io.BytesIO(image_bytes))
    encodings = face_recognition_module.face_encodings(image)
    if not encodings:
        raise ValidationError("No face detected.")

    repositories.store_face_encoding(student_id, encodings[0].tobytes())
    invalidate_face_cache()
    load_face_cache(force=True)
    logger.info("Face registered for student_id=%s", student_id)


def _check_recognition_rate_limit(remote_addr):
    ip = remote_addr or "unknown"
    now = time.time()
    with _recognition_rate_lock:
        last = _last_recognition_by_ip.get(ip, 0)
        if (now - last) < RECOGNITION_MIN_INTERVAL_SECONDS:
            raise TooManyRequestsError("Please slow down.")
        _last_recognition_by_ip[ip] = now


def recognize(schedule_id, image_data_url, face_recognition_module, remote_addr):
    if not _recognition_semaphore.acquire(blocking=False):
        raise ServiceUnavailableError("Recognition is busy. Try again.")

    try:
        _check_recognition_rate_limit(remote_addr)

        schedule = repositories.get_schedule(schedule_id)
        if schedule["is_free_period"]:
            return {
                "status": "ok",
                "recognized": [],
                "message": "Free period. Attendance not recorded.",
            }

        known_faces = load_face_cache()
        if not known_faces:
            raise ValidationError("No registered faces available.")

        image_bytes = decode_image_data_url(image_data_url)
        image = face_recognition_module.load_image_file(io.BytesIO(image_bytes))
        face_locations = face_recognition_module.face_locations(image)
        encodings = face_recognition_module.face_encodings(image, face_locations)

        if not encodings:
            return {"status": "ok", "recognized": [], "message": "No face detected."}

        known_encodings = [face["encoding"] for face in known_faces]
        matches_by_id = {}
        for encoding in encodings:
            matches = face_recognition_module.compare_faces(
                known_encodings,
                encoding,
                tolerance=0.5,
            )
            if True not in matches:
                continue
            match_index = matches.index(True)
            match = known_faces[match_index]
            matches_by_id[match["student_id"]] = match["name"]

        if not matches_by_id:
            return {"status": "ok", "recognized": [], "message": "No matches found."}

        result = repositories.record_attendance_for_schedule(
            schedule_id,
            list(matches_by_id.keys()),
        )
        recognized_names = [
            matches_by_id[student_id]
            for student_id in result["inserted"]
            if student_id in matches_by_id
        ]

        if recognized_names:
            return {
                "status": "ok",
                "recognized": recognized_names,
                "message": "Attendance updated.",
            }

        return {"status": "ok", "recognized": [], "message": "No new attendance records."}
    finally:
        _recognition_semaphore.release()


def get_attendance_summary():
    subject_warnings = []
    overall_data = {}

    for row in repositories.get_attendance_summary_rows():
        total = row["total_classes"] or 0
        present = row["present_classes"] or 0
        percentage = (present / total) * 100 if total > 0 else 0
        roll_no = row["roll_no"]

        subject_warnings.append(
            {
                "roll_no": roll_no,
                "subject": row["subject_name"],
                "percentage": round(percentage, 2),
                "status": "WARNING" if percentage < 75 else "OK",
            }
        )

        overall_data.setdefault(roll_no, {"present": 0, "total": 0})
        overall_data[roll_no]["present"] += present
        overall_data[roll_no]["total"] += total

    exam_warnings = []
    for roll_no, data in overall_data.items():
        overall_percentage = (
            (data["present"] / data["total"]) * 100 if data["total"] > 0 else 0
        )
        exam_warnings.append(
            {
                "roll_no": roll_no,
                "overall_percentage": round(overall_percentage, 2),
                "exam_status": "NOT ELIGIBLE" if overall_percentage < 75 else "ELIGIBLE",
            }
        )

    return subject_warnings, exam_warnings


def get_final_attendance():
    final_result = []
    for row in repositories.get_final_attendance_rows():
        final_result.append(
            {
                "roll_no": row["roll_no"],
                "subject": row["subject_name"],
                "date": row["date"],
                "present_count": row["present_count"],
                "final_status": "PRESENT" if row["present_count"] >= 3 else "ABSENT",
            }
        )
    return final_result


def get_dashboard_view_model():
    data = repositories.get_dashboard_data()
    subject_warnings, exam_warnings = get_attendance_summary()

    metrics = {
        "total_students": data["total_students"],
        "active_classes": data["active_classes"],
        "running_now": data["running_now"],
        "attendance_rate": 0,
        "warnings": sum(
            1 for warning in exam_warnings if warning["exam_status"] == "NOT ELIGIBLE"
        ),
    }

    mix = data["mix"] or {}
    present_count = mix.get("present_count") or 0
    late_count = mix.get("late_count") or 0
    total_count = mix.get("total_count") or 0
    donut = {
        "present": 0,
        "late": 0,
        "absent": 0,
        "center_value": "0%",
        "center_label": "No data",
        "empty": True,
    }
    if total_count:
        present_pct = round((present_count / total_count) * 100)
        late_pct = round((late_count / total_count) * 100)
        absent_pct = max(0, 100 - present_pct - late_pct)
        donut = {
            "present": present_pct,
            "late": late_pct,
            "absent": absent_pct,
            "center_value": f"{present_pct}%",
            "center_label": "Present",
            "empty": False,
        }
        metrics["attendance_rate"] = present_pct

    warning_by_subject = {}
    for warning in subject_warnings:
        if warning["status"] == "WARNING":
            subject = warning["subject"]
            warning_by_subject[subject] = warning_by_subject.get(subject, 0) + 1

    alerts = [
        {
            "title": f"{subject} / {count} students",
            "subtitle": "Below 75% attendance",
            "status": "Action",
            "tone": "danger",
        }
        for subject, count in sorted(
            warning_by_subject.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:2]
    ]

    return {
        "metrics": metrics,
        "attendance_trend": data["attendance_trend"],
        "donut": donut,
        "upcoming_classes": data["upcoming_classes"],
        "alerts": alerts,
    }


def get_export_data():
    students, subjects, daily_rows = repositories.get_export_rows()
    totals = {}
    overall = {}
    subject_dates = {}

    for row in daily_rows:
        student_id = row["student_id"]
        subject_id = row["subject_id"]
        present = 1 if (row["present_count"] or 0) >= 3 else 0
        totals.setdefault((student_id, subject_id), {"present": 0, "total": 0})
        totals[(student_id, subject_id)]["present"] += present
        totals[(student_id, subject_id)]["total"] += 1
        overall.setdefault(student_id, {"present": 0, "total": 0})
        overall[student_id]["present"] += present
        overall[student_id]["total"] += 1
        subject_dates.setdefault(subject_id, set()).add(row["date"])

    return {
        "students": students,
        "subjects": subjects,
        "totals": totals,
        "overall": overall,
        "subject_dates": subject_dates,
    }
