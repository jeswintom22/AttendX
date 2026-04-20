import logging
import os
import tempfile

from flask import (
    Flask,
    after_this_request,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_cors import CORS

from app_errors import AppError, ConflictError, DatabaseBusyError
import repositories
import services
from validators import (
    DAY_NAMES,
    ValidationError,
    clean_text,
    default_day,
    parse_positive_int,
    parse_student_ids,
    validate_day,
    validate_message_payload,
    validate_schedule_payload,
    validate_student_payload,
)
from logic.export_excel import export_attendance_excel

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("attendx")

secret_key = os.getenv("ATTENDX_SECRET_KEY")
is_production = os.getenv("FLASK_ENV", "").lower() == "production"
if is_production and not secret_key:
    raise RuntimeError("ATTENDX_SECRET_KEY is required in production.")
app.secret_key = secret_key or "attendx-dev-secret-change-me"

app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("ATTENDX_SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("ATTENDX_SESSION_COOKIE_SECURE", "false").lower() == "true"
)
session_cookie_domain = os.getenv("ATTENDX_SESSION_COOKIE_DOMAIN")
if session_cookie_domain:
    app.config["SESSION_COOKIE_DOMAIN"] = session_cookie_domain

cors_origins = os.getenv("ATTENDX_CORS_ORIGINS")
if cors_origins:
    CORS(
        app,
        supports_credentials=True,
        origins=[origin.strip() for origin in cors_origins.split(",") if origin.strip()],
    )

ADMIN_USERNAME = os.getenv("ATTENDX_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ATTENDX_ADMIN_PASSWORD", "admin123")

try:
    import face_recognition  # type: ignore

    FACE_RECOGNITION_AVAILABLE = True
except Exception as exc:  # pragma: no cover - environment dependent
    face_recognition = None
    FACE_RECOGNITION_AVAILABLE = False
    logger.warning("face_recognition import failed: %s", exc)

repositories.ensure_schema()


def json_error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def wants_json():
    if request.is_json:
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept or "json" in accept


def require_admin_json():
    if "admin" not in session:
        return json_error("Unauthorized", 401)
    return None


def require_admin_page():
    if "admin" not in session:
        return redirect(url_for("login"))
    return None


def api_payload():
    return request.get_json(silent=True) or {}


@app.errorhandler(AppError)
def handle_app_error(exc):
    logger.warning("Application error: %s", exc.message)
    if wants_json():
        return json_error(exc.message, exc.status_code)
    return exc.message, exc.status_code


@app.errorhandler(DatabaseBusyError)
def handle_database_busy(exc):
    logger.warning("Database busy: %s", exc.message)
    return json_error(exc.message, 503)


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = clean_text(request.form.get("username"), "Username", max_length=120)
        password = clean_text(request.form.get("password"), "Password", max_length=120)

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = api_payload()
    username = clean_text(data.get("username"), "Username", max_length=120)
    password = clean_text(data.get("password"), "Password", max_length=120)

    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session["admin"] = True
        return jsonify({"status": "ok"})

    logger.info("API login failed for username=%s", username)
    return json_error("Invalid credentials", 401)


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("admin", None)
    return jsonify({"status": "ok"})


@app.route("/api/session", methods=["GET"])
def api_session():
    return jsonify({"status": "ok", "authenticated": "admin" in session})


@app.route("/dashboard")
def dashboard():
    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response

    view_model = services.get_dashboard_view_model()
    return render_template("dashboard.html", **view_model)


@app.route("/register-student", methods=["GET", "POST"])
def register_student():
    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        try:
            student = validate_student_payload(request.form)
            services.create_student(student)
            msg = "Student registered successfully"
        except ConflictError as exc:
            msg = exc.message
        except ValidationError as exc:
            msg = exc.message
        return render_template("register_student.html", msg=msg)

    return render_template("register_student.html")


@app.route("/students", methods=["GET", "POST"])
def view_students():
    if request.method == "POST":
        return api_create_student()
    if wants_json():
        return api_students()

    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response

    return render_template("view_students.html", students=services.list_students())


@app.route("/api/students", methods=["GET"])
def api_students():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    students = [
        {
            "student_id": row["student_id"],
            "roll_no": row["roll_no"],
            "name": row["name"],
            "department": row["department"],
            "semester": row["semester"],
        }
        for row in services.list_students()
    ]
    return jsonify({"status": "ok", "students": students})


@app.route("/api/students", methods=["POST"])
def api_create_student():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    student = validate_student_payload(api_payload())
    created = services.create_student(student)
    return jsonify({"status": "ok", "student": created})


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("login"))


def _safe_schedule_day(raw_day=None):
    try:
        return validate_day(raw_day or default_day())
    except ValidationError:
        return default_day()


@app.route("/schedule", methods=["GET", "POST"])
def schedule():
    if request.method == "POST" and request.is_json:
        return api_create_schedule()
    if request.method == "GET" and wants_json():
        return api_schedule()

    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        day = _safe_schedule_day(request.form.get("day"))
        try:
            payload = validate_schedule_payload(request.form)
            services.create_schedule(payload)
            return redirect(url_for("schedule", day=payload["day"], saved=1))
        except AppError as exc:
            return render_template(
                "schedule.html",
                day=day,
                days=DAY_NAMES,
                schedules=services.fetch_schedule_for_day(day),
                error=exc.message,
            )

    day = _safe_schedule_day(request.args.get("day"))
    msg = "Schedule saved successfully" if request.args.get("saved") else None
    return render_template(
        "schedule.html",
        day=day,
        days=DAY_NAMES,
        schedules=services.fetch_schedule_for_day(day),
        msg=msg,
    )


@app.route("/api/schedule", methods=["GET"])
def api_schedule():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    day = _safe_schedule_day(request.args.get("day"))
    return jsonify(
        {
            "status": "ok",
            "day": day,
            "schedules": services.fetch_schedule_for_day(day),
        }
    )


@app.route("/schedule/today", methods=["GET"])
def api_schedule_today():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    day = default_day()
    return jsonify({"status": "ok", "day": day, "schedules": services.fetch_schedule_for_day(day)})


@app.route("/api/schedule", methods=["POST"])
def api_create_schedule():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    payload = validate_schedule_payload(api_payload())
    created = services.create_schedule(payload)
    return jsonify({"status": "ok", "schedule": created})


@app.route("/send-message", methods=["GET", "POST"])
def send_message():
    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        try:
            content = validate_message_payload(request.form)
            services.create_message(content)
            msg = "Message sent successfully"
        except ValidationError as exc:
            msg = exc.message
        return render_template("send_message.html", msg=msg)

    return render_template("send_message.html")


@app.route("/api/messages", methods=["POST"])
def api_send_message():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    services.create_message(validate_message_payload(api_payload()))
    return jsonify({"status": "ok"})


@app.route("/messages", methods=["POST"])
def messages_json():
    return api_send_message()


@app.route("/display-message")
def display_message():
    return render_template("display_message.html", message=services.get_latest_message())


@app.route("/warnings")
def warnings():
    if wants_json():
        return api_warnings()

    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response

    subject_warnings, exam_warnings = services.get_attendance_summary()
    return render_template(
        "warning.html",
        subject_warnings=subject_warnings,
        exam_warnings=exam_warnings,
    )


@app.route("/api/warnings")
def api_warnings():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    subject_warnings, exam_warnings = services.get_attendance_summary()
    return jsonify(
        {
            "status": "ok",
            "subject_warnings": subject_warnings,
            "exam_warnings": exam_warnings,
        }
    )


def _send_export():
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    temp_path = temp.name
    temp.close()
    export_attendance_excel(temp_path)

    @after_this_request
    def cleanup(response):
        try:
            os.remove(temp_path)
        except OSError:
            logger.warning("Failed to remove temporary export %s", temp_path)
        return response

    return send_file(temp_path, as_attachment=True, download_name="attendance_report.xlsx")


@app.route("/export-excel")
def export_excel():
    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response
    return _send_export()


@app.route("/api/reports/export")
def api_export_excel():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error
    return _send_export()


@app.route("/reports/export")
def reports_export_excel():
    return api_export_excel()


@app.route("/face-register", methods=["GET"])
def face_register():
    redirect_response = require_admin_page()
    if redirect_response:
        return redirect_response

    return render_template("face_register.html", students=services.list_students())


@app.route("/face-register/capture", methods=["POST"])
def face_register_capture():
    if "admin" not in session:
        return json_error("Unauthorized", 401)
    if not FACE_RECOGNITION_AVAILABLE:
        return json_error(
            "face_recognition is not available. Install it to register faces.",
            500,
        )

    payload = api_payload()
    student_id = parse_positive_int(payload.get("student_id"), "student selection")
    services.register_face(student_id, payload.get("image"), face_recognition)
    return jsonify({"status": "ok"})


@app.route("/api/face-register/capture", methods=["POST"])
def api_face_register_capture():
    return face_register_capture()


@app.route("/recognize", methods=["POST"])
def recognize():
    if "admin" not in session:
        return json_error("Unauthorized", 401)
    if not FACE_RECOGNITION_AVAILABLE:
        return json_error(
            "face_recognition is not available. Install it to use recognition.",
            500,
        )

    payload = api_payload()
    schedule_id = parse_positive_int(payload.get("schedule_id"), "schedule id")
    result = services.recognize(
        schedule_id,
        payload.get("image"),
        face_recognition,
        request.remote_addr,
    )
    return jsonify(result)


@app.route("/api/recognize", methods=["POST"])
def api_recognize():
    return recognize()


@app.route("/attendance", methods=["POST"])
def api_attendance():
    auth_error = require_admin_json()
    if auth_error:
        return auth_error

    payload = api_payload()
    schedule_id = parse_positive_int(payload.get("schedule_id"), "schedule id")
    student_ids = parse_student_ids(payload)
    result = services.record_attendance(schedule_id, student_ids)

    if result["free_period"]:
        return jsonify(
            {
                "status": "ok",
                "inserted": [],
                "message": "Free period. Attendance not recorded.",
            }
        )
    return jsonify({"status": "ok", "inserted": result["inserted"]})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
