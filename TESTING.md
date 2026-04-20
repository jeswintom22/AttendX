# Testing Guide

## Manual Checklist

1. Create or activate a virtual environment:
   - `py -3.10 -m venv .venv`
   - `.venv\Scripts\activate`
2. Install dependencies:
   - `.venv\Scripts\python -m pip install --upgrade pip`
   - `.venv\Scripts\python -m pip install -r requirements.txt`
   - `.venv\Scripts\python check_face_stack.py`
3. Set local environment variables:
   - `$env:ATTENDX_SECRET_KEY="dev-secret"`
   - `$env:ATTENDX_ADMIN_USERNAME="admin"`
   - `$env:ATTENDX_ADMIN_PASSWORD="admin123"`
4. Initialize the database:
   - `.venv\Scripts\python db\create_db.py`
   - `.venv\Scripts\python db\insert_sample_data.py`
5. Run automated tests:
   - `.venv\Scripts\python -m unittest discover -s tests -v`
6. Run the app:
   - `.venv\Scripts\python app.py`
7. Login with `admin` / `admin123`.
8. Register a student face:
   - Go to `/face-register`
   - Start camera and click **Capture and Register**
9. Create a schedule entry for today at `/schedule`.
10. Click **Start Camera** on a schedule row and verify:
   - Video opens in a modal
   - Recognized students are listed
   - Attendance is recorded in the DB

## Automated Coverage

The test suite creates an isolated temporary SQLite database and verifies:

- WAL mode initialization.
- Transaction rollback.
- Retry behavior while a write lock is held.
- Subject deduplication before creating the normalized unique index.
- Student, schedule, and attendance route behavior.

## DB Verification

Use SQLite to confirm attendance rows:

```sql
SELECT * FROM Attendance ORDER BY attendance_id DESC LIMIT 5;
```

## API Smoke Tests (Browser Session Required)

These endpoints require an admin session cookie from the browser.

```bash
curl -X POST http://127.0.0.1:5000/face-register/capture \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<YOUR_SESSION_COOKIE>" \
  -d '{"student_id":1,"image":"data:image/jpeg;base64,..."}'

curl -X POST http://127.0.0.1:5000/recognize \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<YOUR_SESSION_COOKIE>" \
  -d '{"schedule_id":1,"image":"data:image/jpeg;base64,..."}'
```
