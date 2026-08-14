#!/usr/bin/env python3
"""Create a unique task brief and result packet without overwriting prior work."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from memory_lib import atomic_write
from collaboration_lib import (
    load_collaboration,
    require_enabled_worker,
    require_orchestrator,
    write_json,
)
from workflow_lib import (
    PERMISSION_DEFAULTS,
    TASK_ID_RE,
    git_head,
    workflow_preflight,
    write_status_for_started_task,
)

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = (
    SKILL_ROOT / "templates"
    if (SKILL_ROOT / "templates").is_dir()
    else SKILL_ROOT / "assets" / "templates"
)


def valid_title(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 200 or "\n" in cleaned or "\r" in cleaned:
        raise argparse.ArgumentTypeError("title must be a non-empty single line up to 200 characters")
    return cleaned


def valid_target(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 300 or "\n" in cleaned or "\r" in cleaned:
        raise argparse.ArgumentTypeError("target or scope must be a non-empty single line up to 300 characters")
    return cleaned


def render(name: str, values: dict[str, str]) -> str:
    content = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", value)
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--id", required=True, dest="task_id")
    parser.add_argument("--title", required=True, type=valid_title)
    parser.add_argument("--actor", default="codex")
    parser.add_argument("--worker", choices=("claude-code", "hermes", "opencode"))
    parser.add_argument(
        "--file-edits", choices=("allow", "deny"), default=PERMISSION_DEFAULTS["permission_file_edits"]
    )
    parser.add_argument(
        "--dependency-install",
        choices=("allow", "ask", "deny"),
        default=PERMISSION_DEFAULTS["permission_dependency_install"],
    )
    parser.add_argument(
        "--git-commit", choices=("allow", "deny"), default=PERMISSION_DEFAULTS["permission_git_commit"]
    )
    parser.add_argument(
        "--git-push", choices=("allow", "deny"), default=PERMISSION_DEFAULTS["permission_git_push"]
    )
    parser.add_argument("--git-push-target", type=valid_target, default="none")
    parser.add_argument(
        "--local-database",
        choices=("allow", "deny"),
        default=PERMISSION_DEFAULTS["permission_local_database"],
    )
    parser.add_argument(
        "--deploy", choices=("allow", "deny"), default=PERMISSION_DEFAULTS["permission_deploy"]
    )
    parser.add_argument("--deploy-target", type=valid_target, default="none")
    parser.add_argument(
        "--external-mutation",
        choices=("allow", "deny"),
        default=PERMISSION_DEFAULTS["permission_external_mutation"],
    )
    parser.add_argument("--external-scope", type=valid_target, default="none")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")
    if not TASK_ID_RE.fullmatch(args.task_id):
        parser.error("task ID must contain lowercase letters, digits, and single hyphens")
    collaboration = load_collaboration(root)
    try:
        require_orchestrator(root, args.actor, "start-task")
        if collaboration:
            if not args.worker:
                parser.error("--worker is required for a v4 project and is selected per task")
            require_enabled_worker(root, args.worker)
        elif args.worker:
            parser.error("--worker requires v4 project collaboration configuration")
    except ValueError as exc:
        parser.error(str(exc))
    scoped_permissions = (
        (args.git_push, args.git_push_target, "git-push", "git-push-target"),
        (args.deploy, args.deploy_target, "deploy", "deploy-target"),
        (args.external_mutation, args.external_scope, "external-mutation", "external-scope"),
    )
    for permission, target, permission_name, target_name in scoped_permissions:
        if permission == "allow" and target.lower() == "none":
            parser.error(f"--{target_name} is required when --{permission_name}=allow")
        if permission == "deny" and target.lower() != "none":
            parser.error(f"--{target_name} must be omitted when --{permission_name}=deny")

    try:
        preflight = workflow_preflight(root, "start-task", args.actor)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    if not preflight["gate"]["allowed"]:
        parser.error(
            f"workflow gate {preflight['gate']['code']}: {preflight['gate']['message']}"
        )

    task_dir = root / ".ai-workflow" / "tasks" / args.task_id
    if task_dir.exists():
        parser.error(f"task already exists; refusing to overwrite: {task_dir}")
    task_dir.mkdir(parents=True)
    values = {
        "TASK_ID": args.task_id,
        "TITLE": args.title,
        "TITLE_YAML": json.dumps(args.title, ensure_ascii=False),
        "DATE": dt.date.today().isoformat(),
        "HEAD": git_head(root, short=True),
        "PERMISSION_FILE_EDITS": args.file_edits,
        "PERMISSION_DEPENDENCY_INSTALL": args.dependency_install,
        "PERMISSION_GIT_COMMIT": args.git_commit,
        "PERMISSION_GIT_PUSH": args.git_push,
        "PERMISSION_GIT_PUSH_TARGET_YAML": json.dumps(args.git_push_target, ensure_ascii=False),
        "PERMISSION_LOCAL_DATABASE": args.local_database,
        "PERMISSION_DEPLOY": args.deploy,
        "PERMISSION_DEPLOY_TARGET_YAML": json.dumps(args.deploy_target, ensure_ascii=False),
        "PERMISSION_EXTERNAL_MUTATION": args.external_mutation,
        "PERMISSION_EXTERNAL_SCOPE_YAML": json.dumps(args.external_scope, ensure_ascii=False),
        "ORCHESTRATOR_AGENT": args.actor,
        "EXECUTION_AGENT": args.worker or "none",
        "ROLE_POLICY": "orchestrator-worker" if collaboration else "legacy",
    }
    atomic_write(task_dir / "brief.md", render("TASK_BRIEF.md", values))
    atomic_write(task_dir / "result.md", render("TASK_RESULT.md", values))
    if collaboration:
        write_json(
            task_dir / "coordination.json",
            {
                "task_id": args.task_id,
                "orchestrator": args.actor,
                "execution_agent": args.worker,
                "active_agent": args.actor,
                "phase": "ORCHESTRATION",
                "handoff_from": None,
                "handoff_to": None,
                "handoff_at": None,
                "handoff_commit": None,
                "handoff_fingerprint": None,
                "next_action": "由编排 Agent 完善任务范围、验收条件、权限和架构影响。",
            },
        )
    write_status_for_started_task(root, args.task_id, args.title)
    print(f"CREATE  {task_dir / 'brief.md'}")
    print(f"CREATE  {task_dir / 'result.md'}")
    if collaboration:
        print(f"CREATE  {task_dir / 'coordination.json'}")
        print(f"WORKER   {args.worker}")
    print("NEXT    fill confirmed facts, dirty worktree state, acceptance, and validation commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
