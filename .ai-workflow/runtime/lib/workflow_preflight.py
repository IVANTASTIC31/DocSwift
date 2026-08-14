#!/usr/bin/env python3
"""Inspect project and task state before a guarded workflow transition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflow_lib import workflow_preflight


INTENTS = ("start-project", "start-task", "resume-task", "prepare-commit", "handoff")


def render_text(report: dict[str, object]) -> str:
    gate = report["gate"]
    active = report["active_task"]
    recent = report["recent_task"]
    lines = [
        f"INTENT   {report['intent']}",
        f"ACTOR    {report['actor']['id']} ({report['actor']['role']})",
        f"PROJECT  {report['project_state']}",
        f"PYTHON   {report['environment']['python_version']}",
        f"WRITABLE {'yes' if report['environment']['root_writable'] else 'no'}",
        "GIT      "
        + f"tool={'yes' if report['git']['git_available'] else 'no'}, "
        + f"project-repo={'yes' if report['git']['is_repository'] else 'no'}, "
        + f"worktree={report['git']['worktree']}",
        f"TASK     {active['id']} ({active['status']})" if active else "TASK     none",
        f"RECENT   {recent['id']} ({recent['status']})" if recent else "RECENT   none",
        f"GATE     {gate['code']}",
        f"ALLOWED  {'yes' if gate['allowed'] else 'no'}",
        f"MESSAGE  {gate['message']}",
    ]
    if gate["actions"]:
        lines.append("ACTIONS  " + ", ".join(gate["actions"]))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--intent", required=True, choices=INTENTS)
    parser.add_argument("--actor", default="codex")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")
    try:
        report = workflow_preflight(root, args.intent, args.actor)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0 if report["gate"]["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
