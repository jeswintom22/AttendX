import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repositories import ensure_schema


if __name__ == "__main__":
    ensure_schema()
    print("Database setup complete.")
