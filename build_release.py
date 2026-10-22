"""Build a clean, source-only Windows distribution of Pulse PC."""
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "Pulse-PC-1.0.0-Windows-Python.zip"
EXCLUDED = (".github/", "tests/", ".git/", "__pycache__/", ".venv/", ".qt-venv/")
EXCLUDED_FILES = {"build_release.py", ".gitignore"}

def main():
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    included = []
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as archive:
        for name in tracked:
            if not name or name in EXCLUDED_FILES or any(name.startswith(p) for p in EXCLUDED):
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            archive.write(path, arcname=f"Pulse-PC/{name}")
            included.append(name)
    assert "install.bat" in included and "launcher.py" in included
    assert "requirements.txt" in included and "PulsePC.pyw" in included
    print(f"Created {OUTPUT.name} ({len(included)} source files)")

if __name__ == "__main__":
    main()
