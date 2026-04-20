from logic.calculate_attendance import subject_attendance


def calculate_attendance_percentage(student_id, subject_id):
    return subject_attendance(student_id, subject_id)


if __name__ == "__main__":
    percentage = calculate_attendance_percentage(1, 1)
    print(f"Attendance percentage for Student 1 in Subject 1: {percentage}%")
