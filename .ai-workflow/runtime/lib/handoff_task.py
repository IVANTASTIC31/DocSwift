#!/usr/bin/env python3
"""Create or accept a formal task handoff between the orchestrator and one worker."""

from __future__ import annotations

import argparse
from pathlib import Path

from collaboration_lib import (
    actor_role,
    handoff_fingerprint,
    load_collaboration,
    load_coordination,
    protected_document_drift,
    protected_document_hashes,
    require_enabled_worker,
    validate_coordination,
    write_json,
)
from workflow_lib import TASK_ID_RE, git_head, now_iso, task_status


def single_line(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 500 or "\n" in cleaned or "\r" in cleaned:
        raise argparse.ArgumentTypeError("value must be a non-empty single line up to 500 characters")
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--id", required=True, dest="task_id")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--from", dest="handoff_from")
    parser.add_argument("--to", dest="handoff_to")
    parser.add_argument("--next-action", type=single_line)
    parser.add_argument("--accept", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")
    if not TASK_ID_RE.fullmatch(args.task_id):
        parser.error("invalid task ID")
    collaboration = load_collaboration(root)
    coordination = load_coordination(root, args.task_id)
    if collaboration is None or coordination is None:
        parser.error("v4 collaboration and task coordination are required")
    problems = validate_coordination(coordination, args.task_id)
    if problems:
        parser.error("invalid coordination: " + "; ".join(problems))

    if args.accept:
        if args.handoff_from or args.handoff_to or args.next_action:
            parser.error("--accept cannot be combined with --from, --to, or --next-action")
        if coordination.get("handoff_to") != args.actor or coordination.get("active_agent") != args.actor:
            parser.error("no pending handoff exists for this actor")
        current = handoff_fingerprint(root)
        recorded = coordination.get("handoff_fingerprint")
        if not recorded or current != recorded:
            parser.error(
                f"handoff snapshot changed before acceptance: recorded={recorded}, current={current}"
            )
        role = actor_role(root, args.actor)
        coordination["handoff_to"] = None
        coordination["phase"] = "IMPLEMENTATION" if role == "worker" else "READY_FOR_ORCHESTRATOR"
        coordination["accepted_at"] = now_iso()
        coordination["accepted_fingerprint"] = current
        write_json(root / ".ai-workflow" / "tasks" / args.task_id / "coordination.json", coordination)
        print(f"ACCEPT   {args.actor}")
        print(f"PHASE    {coordination['phase']}")
        return 0

    if not args.handoff_from or not args.handoff_to or not args.next_action:
        parser.error("handoff requires --from, --to, and --next-action")
    if args.actor != args.handoff_from:
        parser.error("actor must equal --from")
    if coordination.get("handoff_to"):
        parser.error(f"handoff already awaits acceptance by {coordination['handoff_to']}")
    if coordination.get("active_agent") != args.handoff_from:
        parser.error(f"non-active actor cannot hand off; active={coordination.get('active_agent')}")
    orchestrator = collaboration["orchestrator"]
    execution_agent = coordination["execution_agent"]
    if {args.handoff_from, args.handoff_to} != {orchestrator, execution_agent}:
        parser.error("handoff must stay within the task's orchestrator/worker pair")
    if args.handoff_to != orchestrator:
        require_enabled_worker(root, args.handoff_to)
        if task_status(root, args.task_id) not in {"PLANNED", "IN_PROGRESS"}:
            parser.error("only a planned or in-progress task can be assigned to a worker")
        coordination["protected_documents"] = protected_document_hashes(root, args.task_id)
        phase = "PENDING_WORKER_ACCEPTANCE"
    else:
        drift = protected_document_drift(
            root, args.task_id, coordination.get("protected_documents", {})
        )
        if drift:
            parser.error("worker changed orchestrator-owned documents: " + ", ".join(drift))
        phase = "PENDING_ORCHESTRATOR_ACCEPTANCE"
    fingerprint = handoff_fingerprint(root)
    coordination.update(
        {
            "active_agent": args.handoff_to,
            "phase": phase,
            "handoff_from": args.handoff_from,
            "handoff_to": args.handoff_to,
            "handoff_at": now_iso(),
            "handoff_commit": git_head(root),
            "handoff_fingerprint": fingerprint,
            "next_action": args.next_action,
        }
    )
    write_json(root / ".ai-workflow" / "tasks" / args.task_id / "coordination.json", coordination)
    print(f"HANDOFF  {args.handoff_from} -> {args.handoff_to}")
    print(f"PHASE    {phase}")
    print(f"SNAPSHOT {fingerprint}")
    print("NEXT     target actor must accept before controlled work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
