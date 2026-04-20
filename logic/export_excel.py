import re

from openpyxl import Workbook

from services import get_export_data


def _percentage(values):
    total = values.get("total", 0) if values else 0
    present = values.get("present", 0) if values else 0
    return round((present / total) * 100, 2) if total else 0


def _safe_sheet_title(title, used):
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", title or "Subject").strip() or "Subject"
    cleaned = cleaned[:31]
    candidate = cleaned
    counter = 1
    while candidate in used:
        suffix = f" {counter}"
        candidate = f"{cleaned[:31 - len(suffix)]}{suffix}"
        counter += 1
    used.add(candidate)
    return candidate


def export_attendance_excel(file_path="attendance_report.xlsx"):
    data = get_export_data()
    wb = Workbook()
    ws = wb.active
    ws.title = "Overall Attendance"

    ws.append(["Roll No", "Name", "Department", "Semester", "Overall Attendance (%)"])
    for student in data["students"]:
        ws.append(
            [
                student["roll_no"],
                student["name"],
                student["department"],
                student["semester"],
                _percentage(data["overall"].get(student["student_id"])),
            ]
        )

    used_titles = {ws.title}
    for subject in data["subjects"]:
        sheet_title = _safe_sheet_title(subject["subject_name"], used_titles)
        subject_ws = wb.create_sheet(title=sheet_title)
        subject_ws.append(["Roll No", "Name", "Attendance %"])

        for student in data["students"]:
            subject_ws.append(
                [
                    student["roll_no"],
                    student["name"],
                    _percentage(
                        data["totals"].get((student["student_id"], subject["subject_id"]))
                    ),
                ]
            )

    wb.save(file_path)
