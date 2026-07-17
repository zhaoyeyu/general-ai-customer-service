from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache"}
FORBIDDEN_FILES = {".env", ".env.local", ".master.key", "customer_service.db"}
TEXT_PATTERNS = {
    "API key": re.compile(r"sk-" + r"(?:or-v1-|proj-)?[A-Za-z0-9_-]{20,}"),
    "local user path": re.compile(r"[A-Za-z]:\\" + r"Users\\[^\\]+\\", re.IGNORECASE),
    "private workspace path": re.compile(r"[A-Za-z]:\\" + r"myproject\\", re.IGNORECASE),
    "clipboard artifact": re.compile(r"codex-" + r"clipboard", re.IGNORECASE),
}


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if path.name in FORBIDDEN_FILES or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log"}:
            findings.append(f"forbidden file: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in TEXT_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {relative}")

    if findings:
        print("Public-boundary check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Public-boundary check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
