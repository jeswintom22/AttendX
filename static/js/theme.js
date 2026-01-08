const toggleTheme = () => {
    document.body.classList.toggle("dark");
    localStorage.setItem(
        "attendx-theme",
        document.body.classList.contains("dark") ? "dark" : "light"
    );
};

// Load saved theme
window.addEventListener("load", () => {
    if (localStorage.getItem("attendx-theme") === "dark") {
        document.body.classList.add("dark");
    }
});
