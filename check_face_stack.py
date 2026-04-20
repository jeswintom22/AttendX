import importlib
import sys


def check(module_name):
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        print(f"[FAIL] {module_name}: {exc}")
        return False

    version = getattr(module, "__version__", "installed")
    print(f"[OK] {module_name}: {version}")
    return True


if __name__ == "__main__":
    print(f"Python: {sys.version}")
    checks = [
        check("numpy"),
        check("PIL.Image"),
        check("dlib"),
        check("face_recognition"),
    ]
    if not all(checks):
        print(
            "\nFace registration needs NumPy, Pillow, dlib, and face_recognition "
            "to import cleanly. If this fails on Python 3.13, recreate the venv "
            "with Python 3.10 or 3.11 and reinstall requirements."
        )
        raise SystemExit(1)

    print("\nFace recognition stack is ready.")
