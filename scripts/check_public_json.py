"""Check a local public output directory without exposing private configuration."""

from pathlib import Path
import sys

# Permit the plan's exact command from a fresh checkout without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from torehancast.public_json import main

if __name__ == "__main__":
    raise SystemExit(main())
