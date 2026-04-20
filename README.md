# AttendX - AI-Powered Attendance Management System

AttendX is a comprehensive attendance management system that uses facial recognition technology to automate student attendance tracking. Built with Python Flask and OpenCV, it provides an intuitive web interface for administrators to manage students, subjects, and attendance records.

## Features

- **Student Registration**: Register students with roll number, name, department, and semester
- **Face Recognition**: Automated attendance marking using facial recognition
- **Attendance Tracking**: Real-time attendance monitoring with percentage calculations
- **Eligibility Checking**: Automatic eligibility determination based on attendance thresholds (75%)
- **Reports & Analytics**: Generate Excel reports and view attendance statistics
- **Web Dashboard**: User-friendly web interface for all operations
- **Database Integration**: SQLite database for reliable data storage

## Technology Stack

- **Backend**: Python Flask
- **Frontend**: HTML, CSS, JavaScript
- **AI/ML**: OpenCV, face_recognition library
- **Database**: SQLite
- **Computer Vision**: Haar Cascade Classifiers

## Installation

### Prerequisites

- Python 3.10 or 3.11 recommended
- Webcam/Camera device
- Git

The face recognition dependency stack includes compiled packages (`dlib`,
`Pillow`, and `numpy`). Python 3.13 is not recommended for this project because
those packages may install without working binary extensions on Windows.

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd AttendX
   ```

2. **Create virtual environment**
   ```bash
   py -3.10 -m venv .venv
   .venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**
   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   python check_face_stack.py
   ```

4. **Configure environment variables**
   ```bash
   set ATTENDX_SECRET_KEY=change-me
   set ATTENDX_ADMIN_USERNAME=admin
   set ATTENDX_ADMIN_PASSWORD=change-me-too
   ```

5. **Set up the database**
   ```bash
   python db/create_db.py
   python db/insert_sample_data.py
   ```

6. **Run the application**
   ```bash
   python app.py
   ```

7. **Access the application**
   - Open your browser and go to `http://127.0.0.1:5000`
   - Default development login: `admin` / `admin123`

## Production Configuration

Set these environment variables before deployment:

```
ATTENDX_SECRET_KEY=<strong random secret>
ATTENDX_ADMIN_USERNAME=<admin username>
ATTENDX_ADMIN_PASSWORD=<strong password>
ATTENDX_DB_PATH=/absolute/path/to/attendance.db
ATTENDX_CORS_ORIGINS=https://your-frontend.example
ATTENDX_SESSION_COOKIE_SECURE=true
ATTENDX_SESSION_COOKIE_SAMESITE=None
ATTENDX_RECOGNITION_MAX_WORKERS=1
ATTENDX_FACE_CACHE_TTL_SECONDS=60
```

SQLite is now configured with WAL mode, busy timeouts, transaction rollback, and retry handling for short write-lock contention. For a larger multi-user deployment, replace SQLite with PostgreSQL so writes can scale beyond SQLite's single-writer model.

## Frontend Integration

AttendX supports a separate frontend that communicates via JSON and uses session cookies.

Set these environment variables for local development:

```
ATTENDX_CORS_ORIGINS=http://localhost:5173
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAMESITE=None
```

For production, set `ATTENDX_CORS_ORIGINS` to your hosted frontend URL and keep
`SESSION_COOKIE_SECURE=true`.

## Usage

### Student Registration

1. Log in to the admin dashboard
2. Navigate to "Register Student"
3. Fill in student details (roll number, name, department, semester)
4. Open `/face-register` from the dashboard
5. Select a student, start the camera, and capture a face encoding

### Taking Attendance

1. Open `/schedule` and pick the day
2. Click **Start Camera** for a schedule row
3. The system performs live recognition and marks attendance automatically

### Viewing Reports

- Access the dashboard to view student lists
- Generate Excel reports using the export functionality
- Check attendance percentages and eligibility status

## Project Structure

```
AttendX/
├── app.py                 # Main Flask application
├── ai/                    # AI and computer vision modules
│   ├── face_detection.py
│   ├── face_recognition_live.py
│   ├── register_student.py
│   └── haarcascade_frontalface_default.xml
├── db/                    # Database setup and sample data
├── logic/                 # Business logic modules
├── static/                # CSS, JS, and image assets
├── templates/             # HTML templates
├── tests/                 # Unit tests
└── data/                  # Student face data storage
```

## API Endpoints

- `GET /` - Login page
- `POST /` - Login authentication
- `GET /dashboard` - Admin dashboard
- `GET/POST /register-student` - Student registration
- `GET /students` - View registered students
- `POST /students` - Create student (JSON)
- `GET /reports` - Attendance reports
- `GET /schedule` - Schedule management + live recognition
- `GET /schedule/today` - Today's schedule (JSON)
- `POST /messages` - Send message (JSON)
- `GET /warnings` - Warnings (JSON when Accept header includes application/json)
- `GET /reports/export` - Export Excel report
- `POST /attendance` - Record attendance for recognized students (JSON)
- `GET /face-register` - In-browser face registration
- `POST /face-register/capture` - Face capture endpoint
- `POST /recognize` - Live recognition endpoint

### JSON API (for Vercel frontend)

- `POST /api/login`
- `POST /api/logout`
- `GET /api/session`
- `GET /api/students`
- `POST /api/students`
- `GET /api/schedule`
- `POST /api/schedule`
- `POST /api/face-register/capture`
- `POST /api/recognize`
- `GET /api/warnings`
- `POST /api/messages`
- `GET /api/reports/export`

See `INTEGRATION.md` for CORS and cookie configuration.

## Testing

Run the test suite:
```bash
python -m unittest discover -s tests -v
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions, please create an issue in the repository or contact the development team.

---

**Note**: Ensure your camera is properly configured and accessible for face recognition features to work correctly.
Camera access typically requires HTTPS when not running on localhost.
