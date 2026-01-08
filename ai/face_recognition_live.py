import cv2
import face_recognition
import os
import warnings

# Optional: hide harmless warnings
warnings.filterwarnings("ignore", category=UserWarning)

KNOWN_FACES_DIR = "data/students"

known_encodings = []
known_names = []

print("Loading student face data...")

# Load known faces
for folder in os.listdir(KNOWN_FACES_DIR):
    folder_path = os.path.join(KNOWN_FACES_DIR, folder)

    # Skip non-directories
    if not os.path.isdir(folder_path):
        continue

    name = folder  # ✅ use roll number / folder name directly

    for image_name in os.listdir(folder_path):
        image_path = os.path.join(folder_path, image_name)

        # Skip non-image files
        if not image_name.lower().endswith((".jpg", ".png", ".jpeg")):
            continue

        image = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(image)

        if encodings:
            known_encodings.append(encodings[0])
            known_names.append(name)

print("Face data loaded successfully")

# Camera (0 is default webcam)
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Camera not accessible")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        break

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    face_locations = face_recognition.face_locations(rgb_frame)
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
        matches = face_recognition.compare_faces(
            known_encodings, face_encoding, tolerance=0.5
        )

        name = "Unknown"

        if True in matches:
            matched_index = matches.index(True)
            name = known_names[matched_index]

        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.putText(
            frame,
            name,
            (left, top - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0),
            2
        )

    cv2.imshow("AttendX | Face Recognition (Press Q to Exit)", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
