"""Print the project tree (heavy dirs pruned) plus a small LOC summary.

Used to keep the README's tree honest — run from the repo root:

    python tools/tree.py            # tree + LOC
    python tools/tree.py --no-loc
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "data",
    "shots",
    ".vite",
}
SKIP_FILES = {".env", "package-lock.json"}
LANG_BY_SUFFIX = {
    ".py": "Python",
    ".vue": "Vue",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".css": "CSS",
    ".html": "HTML",
    ".json": "JSON",
    ".md": "Markdown",
    ".yml": "YAML",
    ".conf": "Nginx",
    ".txt": "Text",
}


def walk(directory: Path, prefix: str = "") -> list[str]:
    entries = sorted(
        (p for p in directory.iterdir() if p.name not in SKIP_DIRS and p.name not in SKIP_FILES),
        key=lambda p: (p.is_file(), p.name.lower()),
    )
    lines: list[str] = []
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        branch = "└── " if last else "├── "
        suffix = "" if entry.is_dir() else f"  ({count_lines(entry)})" if count_lines(entry) else ""
        lines.append(f"{prefix}{branch}{entry.name}{suffix}")
        if entry.is_dir():
            lines.extend(walk(entry, prefix + ("    " if last else "│   ")))
    return lines


def count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def loc_summary() -> list[str]:
    totals: dict[str, list[int]] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        language = LANG_BY_SUFFIX.get(path.suffix)
        if not language:
            continue
        entry = totals.setdefault(language, [0, 0])
        entry[0] += count_lines(path)
        entry[1] += 1
    lines = [f"  {language:<12} {files:>3} files  {count:>6} lines" for language, (count, files) in sorted(totals.items())]
    total = sum(count for count, _ in totals.values())
    lines.append(f"  {'TOTAL':<12} {sum(files for _, files in totals.values()):>3} files  {total:>6} lines")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="project tree + LOC")
    parser.add_argument("--no-loc", action="store_true", help="skip the LOC summary")
    args = parser.parse_args()

    print(f"{ROOT.name}/")
    print("\n".join(walk(ROOT)))
    if not args.no_loc:
        print("\nLOC by language (excluding node_modules/.venv/dist):")
        print("\n".join(loc_summary()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
