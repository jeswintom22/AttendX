(() => {
    const video = document.getElementById("registerVideo");
    const startBtn = document.getElementById("startCameraBtn");
    const captureBtn = document.getElementById("captureBtn");
    const statusEl = document.getElementById("registerStatus");
    const studentSelect = document.getElementById("studentSelect");

    if (!video || !startBtn || !captureBtn || !statusEl || !studentSelect) {
        return;
    }

    let stream = null;

    const setStatus = (message, level = "secondary") => {
        statusEl.textContent = message;
        statusEl.className = `alert alert-${level}`;
    };

    const startCamera = async () => {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = stream;
            setStatus("Camera started.", "success");
        } catch (err) {
            setStatus("Unable to access the camera.", "danger");
        }
    };

    const captureAndRegister = async () => {
        if (!stream || !video.videoWidth) {
            setStatus("Start the camera first.", "warning");
            return;
        }

        const studentId = studentSelect.value;
        if (!studentId) {
            setStatus("Select a student first.", "warning");
            return;
        }

        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 480;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        const dataUrl = canvas.toDataURL("image/jpeg");

        try {
            const response = await fetch("/face-register/capture", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    image: dataUrl,
                    student_id: studentId
                })
            });
            const payload = await response.json().catch(() => ({}));

            if (!response.ok) {
                setStatus(payload.message || "Registration failed.", "danger");
                return;
            }

            setStatus("Face registered successfully.", "success");
        } catch (err) {
            setStatus("Network error while registering.", "danger");
        }
    };

    startBtn.addEventListener("click", startCamera);
    captureBtn.addEventListener("click", captureAndRegister);
})();
