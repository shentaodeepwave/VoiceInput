import sys
from pathlib import Path

# Ensure voiceinput package is on sys.path
sys.path.insert(0, str(Path(__file__).parent / "voiceinput"))

from main import main

if __name__ == "__main__":
    main()
