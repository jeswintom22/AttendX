from logic.calculate_attendance import subject_attendance


def check_attendance_eligibility(student_id, subject_id):
    percentage = subject_attendance(student_id, subject_id)
    return "LOW ATTENDANCE" if percentage < 75 else "ELIGIBLE"


if __name__ == "__main__":
    status = check_attendance_eligibility(1, 1)
    print(f"Eligibility for Student 1 in Subject 1: {status}")
