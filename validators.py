import base64
import binascii
import os
import re
from datetime import datetime

from app_errors import ValidationError

DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

MAX_IMAGE_BYTES = int(os.getenv("ATTENDX_MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))
ROLL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\- ]{0,49}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def clean_text(value, field_name, *, required=False, max_length=255):
    if value is None:
        value = ""
    value = str(value).replace("\x00", "")
    value = " ".join(value.strip().split())
    if required and not value:
        raise ValidationError(f"{field_name} is required.")
    if len(value) > max_length:
        raise ValidationError(f"{field_name} must be {max_length} characters or fewer.")
    return value


def validate_roll(value):
    roll = clean_text(value, "Roll number", required=True, max_length=50)
    if not ROLL_RE.match(roll):
        raise ValidationError("Roll number contains invalid characters.")
    return roll


def parse_positive_int(value, field_name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Invalid {field_name}.") from None
    if parsed <= 0:
        raise ValidationError(f"Invalid {field_name}.")
    return parsed


def parse_student_ids(payload):
    student_ids = payload.get("student_ids") or []
    if not student_ids and payload.get("student_id") is not None:
        student_ids = [payload.get("student_id")]
    if not isinstance(student_ids, list):
        raise ValidationError("Student selection must be a list.")

    parsed = []
    seen = set()
    for value in student_ids:
        student_id = parse_positive_int(value, "student id")
        if student_id not in seen:
            seen.add(student_id)
            parsed.append(student_id)
    if not parsed:
        raise ValidationError("No students provided.")
    return parsed


def validate_day(value):
    day = clean_text(value, "Day", required=True, max_length=16)
    if day not in DAY_NAMES:
        raise ValidationError("Invalid day.")
    return day


def default_day():
    return datetime.today().strftime("%A")


def validate_time(value, field_name):
    value = clean_text(value, field_name, required=True, max_length=5)
    if not TIME_RE.match(value):
        raise ValidationError(f"Invalid {field_name}.")
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        raise ValidationError(f"Invalid {field_name}.") from None
    return value


def validate_time_range(start, end):
    start = validate_time(start, "Start time")
    end = validate_time(end, "End time")
    if start >= end:
        raise ValidationError("End time must be after start time.")
    return start, end


def validate_student_payload(data):
    return {
        "roll_no": validate_roll(data.get("roll_no") if "roll_no" in data else data.get("roll")),
        "name": clean_text(data.get("name"), "Student name", required=True, max_length=120),
        "department": clean_text(
            data.get("department") if "department" in data else data.get("dept"),
            "Department",
            required=False,
            max_length=120,
        ),
        "semester": clean_text(
            data.get("semester") if "semester" in data else data.get("sem"),
            "Semester",
            required=False,
            max_length=30,
        ),
    }


def validate_schedule_payload(data):
    subject_name = clean_text(
        data.get("subject_name") if "subject_name" in data else data.get("subject"),
        "Subject name",
        required=True,
        max_length=120,
    )
    day = validate_day(data.get("day") or default_day())
    start, end = validate_time_range(
        data.get("start_time") if "start_time" in data else data.get("start"),
        data.get("end_time") if "end_time" in data else data.get("end"),
    )
    return {
        "subject_name": subject_name,
        "day": day,
        "start_time": start,
        "end_time": end,
        "is_free_period": 1 if data.get("is_free_period") or data.get("free") else 0,
    }


def validate_message_payload(data):
    return clean_text(data.get("content") if "content" in data else data.get("message"), "Message", required=True, max_length=1000)


def decode_image_data_url(data_url):
    if not data_url:
        raise ValidationError("No image provided.")
    if not isinstance(data_url, str) or "," not in data_url:
        raise ValidationError("Invalid image data.")

    header, encoded = data_url.split(",", 1)
    if not header.startswith("data:image/") or ";base64" not in header:
        raise ValidationError("Invalid image data.")
    if len(encoded) > MAX_IMAGE_BYTES * 2:
        raise ValidationError("Image is too large.")

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError("Invalid image data.") from None

    if not image_bytes:
        raise ValidationError("Invalid image data.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValidationError("Image is too large.")
    return image_bytes
