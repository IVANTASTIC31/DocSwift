#!/usr/bin/env python3
"""Create a project-local lesson candidate; never promote it globally."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

from collaboration_lib import require_orchestrator


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (
    SKILL_ROOT / "templates" / "PROJECT_LESSON.md"
    if (SKILL_ROOT / "templates").is_dir()
    else SKILL_ROOT / "assets" / "templates" / "PROJECT_LESSON.md"
)
LESSON_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
CATEGORIES = {
    "code-editing", "git", "security", "documentation", "testing", "architecture", "operations"
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--id", required=True, dest="lesson_id")
    parser.add_argument("--title", required=True)
    parser.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    parser.add_argument("--actor", default="codex")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")
    if not LESSON_ID.fullmatch(args.lesson_id):
        parser.error("lesson ID must look like LESSON-CATEGORY-001")
    try:
        require_orchestrator(root, args.actor, "propose-lesson")
    except ValueError as exc:
        parser.error(str(exc))

    target = root / "docs" / "lessons" / f"{args.lesson_id.lower()}.md"
    if target.exists():
        parser.error(f"lesson already exists; refusing to overwrite: {target}")
    content = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "LESSON_ID": args.lesson_id,
        "TITLE": args.title,
        "CATEGORY": args.category,
        "DATE": dt.date.today().isoformat(),
    }
    for key, value in replacements.items():
        content = content.replace("{{" + key + "}}", value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    print(f"CREATE  {target}")
    print("NOTE    candidate remains project-local until it is completed, sanitized, and registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
