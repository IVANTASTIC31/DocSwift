#!/usr/bin/env python3
"""Close, pause, or hand off a task while preserving workflow gates."""

from __future__ import annotations

import argparse
from pathlib import Path

from memory_lib import atomic_write, markdown_section
from collaboration_lib import load_coordination, require_orchestrator, write_json
from workflow_lib import (
    frontmatter_updates,
    git_head,
    project_snapshot_fingerprint,
    replace_markdown_section,
    task_audit_state,
    task_result,
    task_status,
    TASK_ID_RE,
    today_iso,
    workflow_preflight,
    write_status_for_closed_task,
)


CLOSE_STATES = ("PAUSED", "BLOCKED", "READY_FOR_REVIEW", "DONE", "ABANDONED")
AUDIT_REQUIRED = {"READY_FOR_REVIEW", "DONE"}


def valid_next_action(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 500 or "\n" in cleaned or "\r" in cleaned:
        raise argparse.ArgumentTypeError("next-action must be a non-empty single line up to 500 characters")
    return cleaned


def valid_task_id(value: str) -> str:
    if not TASK_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("task ID must contain lowercase letters, digits, and single hyphens")
    return value


def validate_completion(text: str) -> list[str]:
    problems: list[str] = []
    outcome = markdown_section(text, "Outcome")
    verification = markdown_section(text, "Verification performed")
    risks = markdown_section(text, "Remaining risks")
    if not outcome:
        problems.append("Outcome is empty")
    if not verification or "Not yet run" in verification or "UNVERIFIED" in verification:
        problems.append("Verification performed is incomplete")
    if not risks or "None recorded yet" in risks:
        problems.append("Remaining risks has not been reviewed")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--id", required=True, dest="task_id", type=valid_task_id)
    parser.add_argument("--status", required=True, choices=CLOSE_STATES)
    parser.add_argument("--next-action", required=True, type=valid_next_action)
    parser.add_argument("--actor", default="codex")
    args = parser.parse_args()
    root = args.root.resolve()
    result_path = task_result(root, args.task_id)
    status_path = root / "docs" / "STATUS.md"
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")
    if not result_path.is_file():
        parser.error(f"task result does not exist: {result_path}")
    if not status_path.is_file():
        parser.error(f"STATUS does not exist: {status_path}")
    try:
        require_orchestrator(root, args.actor, "close-task")
    except ValueError as exc:
        parser.error(str(exc))
    coordination = load_coordination(root, args.task_id)
    if coordination:
        if coordination.get("active_agent") != args.actor or coordination.get("handoff_to"):
            parser.error("orchestrator must formally accept task control before closing the task")
        if args.status in AUDIT_REQUIRED and coordination.get("phase") != "READY_FOR_ORCHESTRATOR":
            parser.error("READY_FOR_REVIEW and DONE require READY_FOR_ORCHESTRATOR phase")

    current_status = task_status(root, args.task_id)
    if current_status in {"DONE", "ABANDONED"}:
        parser.error(f"task is already closed: {args.task_id} ({current_status})")
    preflight = workflow_preflight(root, "start-task", args.actor)
    active = preflight["active_task"]
    if active is None or active["id"] != args.task_id:
        rendered = active["id"] if active else "none"
        parser.error(
            f"refusing to close non-active task {args.task_id}; current active task is {rendered}"
        )

    original = result_path.read_text(encoding="utf-8")
    audit = task_audit_state(root, args.task_id)
    if args.status in AUDIT_REQUIRED:
        if audit["status"] != "PASSED":
            parser.error(
                f"task audit must be PASSED before {args.status}; current={audit['status']}"
            )
        problems = validate_completion(original)
        if problems:
            parser.error("task result is incomplete: " + "; ".join(problems))

    updated = frontmatter_updates(
        original,
        {"status": args.status, "updated": today_iso()},
    )
    updated = replace_markdown_section(updated, "Exact next action", f"1. {args.next_action}")
    atomic_write(result_path, updated)
    write_status_for_closed_task(root, args.task_id, args.status, args.next_action)
    if coordination:
        coordination["phase"] = "CLOSED" if args.status in {"DONE", "ABANDONED"} else args.status
        coordination["next_action"] = args.next_action
        write_json(root / ".ai-workflow" / "tasks" / args.task_id / "coordination.json", coordination)

    if audit["status"] == "PASSED":
        final_fingerprint = project_snapshot_fingerprint(root, args.task_id)
        finalized = frontmatter_updates(
            result_path.read_text(encoding="utf-8"),
            {
                "audited_commit": git_head(root),
                "audited_worktree_fingerprint": final_fingerprint,
            },
        )
        atomic_write(result_path, finalized)

    print(f"TASK     {args.task_id}")
    print(f"STATUS   {args.status}")
    print(f"NEXT     {args.next_action}")
    print("ACTIVE   none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
