#!/usr/bin/env python3
"""Run the read-only project audit and record a current task audit receipt."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from memory_lib import atomic_write
from collaboration_lib import load_coordination, require_orchestrator
from workflow_lib import (
    frontmatter_updates,
    git_head,
    now_iso,
    project_snapshot_fingerprint,
    task_result,
    task_audit_state,
    today_iso,
    TASK_ID_RE,
)


def valid_actor(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 200 or "\n" in cleaned or "\r" in cleaned:
        raise argparse.ArgumentTypeError("reviewed-by must be a non-empty single line up to 200 characters")
    return cleaned


def valid_task_id(value: str) -> str:
    if not TASK_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("task ID must contain lowercase letters, digits, and single hyphens")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--id", required=True, dest="task_id", type=valid_task_id)
    parser.add_argument("--reviewed-by", required=True, type=valid_actor)
    parser.add_argument("--actor", default="codex")
    args = parser.parse_args()
    root = args.root.resolve()
    result_path = task_result(root, args.task_id)
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")
    if not result_path.is_file():
        parser.error(f"task result does not exist: {result_path}")
    try:
        require_orchestrator(root, args.actor, "record-audit")
    except ValueError as exc:
        parser.error(str(exc))
    coordination = load_coordination(root, args.task_id)
    if coordination:
        if coordination.get("active_agent") != args.actor or coordination.get("handoff_to"):
            parser.error("orchestrator must formally accept task control before recording final audit")
        if coordination.get("phase") != "READY_FOR_ORCHESTRATOR":
            parser.error("final audit requires READY_FOR_ORCHESTRATOR phase")

    audit_script = Path(__file__).resolve().parent / "audit_project_memory.py"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    audit = subprocess.run(
        [sys.executable, str(audit_script), "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if audit.stdout:
        print(audit.stdout.rstrip())
    if audit.stderr:
        print(audit.stderr.rstrip(), file=sys.stderr)
    if audit.returncode != 0:
        parser.error("project-memory audit reported structural warnings; refusing to record PASSED")

    original = result_path.read_text(encoding="utf-8")
    fingerprint = project_snapshot_fingerprint(root, args.task_id)
    timestamp = now_iso()
    updated = frontmatter_updates(
        original,
        {
            "updated": today_iso(),
            "last_verified": timestamp,
            "audit_status": "PASSED",
            "audited_at": timestamp,
            "audited_by": args.reviewed_by,
            "audited_commit": git_head(root),
            "audited_worktree_fingerprint": fingerprint,
        },
    )
    atomic_write(result_path, updated)
    state = task_audit_state(root, args.task_id)
    if state["status"] != "PASSED":
        atomic_write(result_path, original)
        parser.error("recorded audit fingerprint did not match the resulting task packet; changes rolled back")
    print(f"AUDIT    PASSED for {args.task_id}")
    print(f"REVIEWER {args.reviewed_by}")
    print(f"SNAPSHOT {fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
