#!/usr/bin/env python3
"""Shared project-state, task-gate, metadata, and audit-fingerprint helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from memory_lib import MANAGED_END, MANAGED_START, atomic_write, metadata_value
from collaboration_lib import (
    actor_role,
    handoff_fingerprint,
    load_collaboration,
    load_coordination,
    validate_collaboration,
    validate_coordination,
)


CORE_DOCUMENTS = ("AGENTS.md", "docs/STATUS.md", "docs/ARCHITECTURE.md")
TASK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TASK_STATES = {
    "PLANNED",
    "IN_PROGRESS",
    "PAUSED",
    "BLOCKED",
    "READY_FOR_REVIEW",
    "DONE",
    "ABANDONED",
}
UNRESOLVED_STATES = {"PLANNED", "IN_PROGRESS", "BLOCKED", "READY_FOR_REVIEW"}
CLOSED_STATES = {"DONE", "ABANDONED"}
AUDIT_FIELDS = {
    "updated",
    "last_verified",
    "audit_status",
    "audited_at",
    "audited_by",
    "audited_commit",
    "audited_worktree_fingerprint",
}
PERMISSION_DEFAULTS = {
    "permission_file_edits": "allow",
    "permission_dependency_install": "ask",
    "permission_git_commit": "deny",
    "permission_git_push": "deny",
    "permission_local_database": "deny",
    "permission_deploy": "deny",
    "permission_external_mutation": "deny",
}
PERMISSION_TARGET_DEFAULTS = {
    "permission_git_push_target": "none",
    "permission_deploy_target": "none",
    "permission_external_scope": "none",
}
SNAPSHOT_EXCLUDED_DIRS = {
    ".git",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "venv",
}


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    return dt.date.today().isoformat()


def run_git(root: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout.rstrip("\r\n")
    except OSError as exc:
        return 127, str(exc)


def git_head(root: Path, short: bool = False) -> str:
    code, top = run_git(root, "rev-parse", "--show-toplevel")
    if code != 0 or Path(top).resolve() != root.resolve():
        return "not-a-git-repository"
    args = ["rev-parse"]
    if short:
        args.append("--short")
    args.append("HEAD")
    code, output = run_git(root, *args)
    return output if code == 0 and output else "not-a-git-repository"


def git_info(root: Path) -> dict[str, Any]:
    git_available = shutil.which("git") is not None
    if not git_available:
        return {
            "git_available": False,
            "is_repository": False,
            "inside_repository": False,
            "top_level": None,
            "head": "git-unavailable",
            "worktree": "unavailable",
        }
    code, top = run_git(root, "rev-parse", "--show-toplevel")
    if code != 0:
        return {
            "git_available": True,
            "is_repository": False,
            "inside_repository": False,
            "top_level": None,
            "head": "not-a-git-repository",
            "worktree": "unavailable",
        }
    top_path = Path(top).resolve()
    is_project_repository = top_path == root.resolve()
    if not is_project_repository:
        return {
            "git_available": True,
            "is_repository": False,
            "inside_repository": True,
            "top_level": str(top_path),
            "head": "not-a-git-repository",
            "worktree": "unavailable",
        }
    status_code, status = run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    return {
        "git_available": True,
        "is_repository": True,
        "inside_repository": True,
        "top_level": str(top_path),
        "head": git_head(root),
        "worktree": "clean" if status_code == 0 and not status else "dirty",
    }


def project_state(root: Path) -> str:
    entries = [item for item in root.iterdir() if item.name != ".git"]
    has_git = git_info(root)["is_repository"]
    if not entries:
        return "empty-git-repository" if has_git else "empty-directory"
    present = sum((root / relative).is_file() for relative in CORE_DOCUMENTS)
    if present == len(CORE_DOCUMENTS):
        return "managed-project"
    if present:
        return "partially-managed-project"
    return "existing-unmanaged-project"


def frontmatter_updates(text: str, updates: dict[str, str]) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?=\r?\n|\Z)", text, re.DOTALL)
    if not match:
        raise ValueError("Markdown file must start with YAML frontmatter")
    lines = match.group(1).splitlines()
    remaining = dict(updates)
    rendered: list[str] = []
    for line in lines:
        field = re.match(r"^([A-Za-z0-9_-]+):", line)
        if field and field.group(1) in remaining:
            key = field.group(1)
            rendered.append(f"{key}: {json.dumps(str(remaining.pop(key)), ensure_ascii=False)}")
        else:
            rendered.append(line)
    for key, value in remaining.items():
        rendered.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    replacement = "---" + newline + newline.join(rendered) + newline + "---"
    return replacement + text[match.end() :]


def replace_markdown_section(text: str, heading: str, content: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    pattern = re.compile(
        rf"(?ms)(^##\s+{re.escape(heading)}\s*$\r?\n)(.*?)(?=^##\s+|\Z)"
    )
    if not pattern.search(text):
        raise ValueError(f"missing Markdown section: {heading}")
    body = content.strip().replace("\n", newline) + newline + newline
    return pattern.sub(lambda match: match.group(1) + body, text, count=1)


def status_active_task(root: Path) -> str | None:
    path = root / "docs" / "STATUS.md"
    if not path.is_file():
        return None
    value = metadata_value(path.read_text(encoding="utf-8"), "active_task")
    if not value or value.lower() in {"none", "null", "n/a"}:
        return None
    return value


def status_last_task(root: Path) -> str | None:
    path = root / "docs" / "STATUS.md"
    if not path.is_file():
        return None
    value = metadata_value(path.read_text(encoding="utf-8"), "last_task")
    if not value or value.lower() in {"none", "null", "n/a"}:
        return None
    return value


def task_dir(root: Path, task_id: str) -> Path:
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("task ID must contain lowercase letters, digits, and single hyphens")
    return root / ".ai-workflow" / "tasks" / task_id


def task_result(root: Path, task_id: str) -> Path:
    return task_dir(root, task_id) / "result.md"


def task_brief(root: Path, task_id: str) -> Path:
    return task_dir(root, task_id) / "brief.md"


def task_status(root: Path, task_id: str) -> str:
    result = task_result(root, task_id)
    if not result.is_file():
        return "MISSING"
    value = metadata_value(result.read_text(encoding="utf-8"), "status")
    return value.upper() if value else "UNKNOWN"


def task_permissions(root: Path, task_id: str) -> dict[str, str]:
    brief = task_brief(root, task_id)
    if not brief.is_file():
        return dict(PERMISSION_DEFAULTS)
    text = brief.read_text(encoding="utf-8")
    permissions = {
        key: metadata_value(text, key) or default
        for key, default in PERMISSION_DEFAULTS.items()
    }
    permissions.update(
        {
            key: metadata_value(text, key) or default
            for key, default in PERMISSION_TARGET_DEFAULTS.items()
        }
    )
    return permissions


def all_task_ids(root: Path) -> list[str]:
    tasks = root / ".ai-workflow" / "tasks"
    if not tasks.is_dir():
        return []
    return sorted(
        path.name for path in tasks.iterdir() if path.is_dir() and TASK_ID_RE.fullmatch(path.name)
    )


def unresolved_tasks(root: Path) -> list[dict[str, str]]:
    return [
        {"id": task_id, "status": status}
        for task_id in all_task_ids(root)
        if (status := task_status(root, task_id)) in UNRESOLVED_STATES
    ]


def _snapshot_paths(root: Path) -> list[str]:
    info = git_info(root)
    if info["is_repository"]:
        code, output = run_git(
            root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        )
        if code == 0:
            return sorted({line.replace("\\", "/") for line in output.split("\0") if line})
    paths: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SNAPSHOT_EXCLUDED_DIRS for part in relative.parts):
            continue
        paths.append(relative.as_posix())
    return sorted(paths)


def _normalized_snapshot_bytes(path: Path, relative: str, task_id: str | None) -> bytes:
    if task_id and relative == f".ai-workflow/tasks/{task_id}/result.md":
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_bytes()
        for field in AUDIT_FIELDS:
            text = re.sub(
                rf"(?m)^{re.escape(field)}:.*$",
                f'{field}: "<normalized>"',
                text,
            )
        return text.encode("utf-8")
    return path.read_bytes()


def project_snapshot_fingerprint(root: Path, task_id: str | None) -> str:
    digest = hashlib.sha256()
    for relative in _snapshot_paths(root):
        path = root / Path(relative)
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"<symlink>")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            digest.update(_normalized_snapshot_bytes(path, relative, task_id))
        else:
            digest.update(b"<deleted>")
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def task_audit_state(root: Path, task_id: str) -> dict[str, str | None]:
    result = task_result(root, task_id)
    if not result.is_file():
        return {"status": "NOT_RUN", "recorded_fingerprint": None, "current_fingerprint": None}
    text = result.read_text(encoding="utf-8")
    recorded_status = (metadata_value(text, "audit_status") or "NOT_RUN").upper()
    recorded = metadata_value(text, "audited_worktree_fingerprint")
    current = project_snapshot_fingerprint(root, task_id)
    if recorded_status == "PASSED" and recorded and recorded == current:
        effective = "PASSED"
    elif recorded_status == "PASSED":
        effective = "STALE"
    else:
        effective = recorded_status
    return {
        "status": effective,
        "recorded_fingerprint": recorded,
        "current_fingerprint": current,
        "audited_at": metadata_value(text, "audited_at"),
        "audited_by": metadata_value(text, "audited_by"),
        "audited_commit": metadata_value(text, "audited_commit"),
    }


def _active_task(root: Path) -> tuple[dict[str, Any] | None, bool, list[dict[str, str]]]:
    declared = status_active_task(root)
    unresolved = unresolved_tasks(root)
    inferred = False
    task_id = declared
    if task_id is not None and task_status(root, task_id) in CLOSED_STATES | {"PAUSED"}:
        task_id = None
    if task_id is None and len(unresolved) == 1:
        task_id = unresolved[0]["id"]
        inferred = True
    if task_id is None:
        return None, inferred, unresolved
    status = task_status(root, task_id)
    return {
        "id": task_id,
        "status": status,
        "declared_in_status": not inferred,
        "permissions": task_permissions(root, task_id),
        "audit": task_audit_state(root, task_id),
    }, inferred, unresolved


def task_summary(root: Path, task_id: str, declared: bool = False) -> dict[str, Any]:
    return {
        "id": task_id,
        "status": task_status(root, task_id),
        "declared_in_status": declared,
        "permissions": task_permissions(root, task_id),
        "audit": task_audit_state(root, task_id),
    }


def workflow_preflight(root: Path, intent: str, actor: str = "codex") -> dict[str, Any]:
    state = project_state(root)
    git = git_info(root)
    agents = root / "AGENTS.md"
    agents_managed = False
    if agents.is_file():
        text = agents.read_text(encoding="utf-8")
        agents_managed = text.count(MANAGED_START) == 1 and text.count(MANAGED_END) == 1
    active, inferred, unresolved = _active_task(root)
    collaboration = load_collaboration(root)
    collaboration_problems = validate_collaboration(collaboration) if collaboration else []
    role = actor_role(root, actor) if not collaboration_problems else "unknown"
    coordination = None
    coordination_problems: list[str] = []
    if active is not None:
        coordination = load_coordination(root, active["id"])
        if coordination is not None:
            coordination_problems = validate_coordination(coordination, active["id"])
    last_task_id = status_last_task(root)
    recent = task_summary(root, last_task_id) if last_task_id else None
    gate = {"code": "none", "allowed": True, "message": "No workflow gate is blocking this intent.", "actions": []}

    environment = {
        "python_version": platform.python_version(),
        "python_supported": tuple(map(int, platform.python_version_tuple()[:2])) >= (3, 10),
        "git_available": git["git_available"],
        "root_writable": os.access(root, os.W_OK),
    }

    if collaboration_problems:
        gate = {
            "code": "collaboration-invalid",
            "allowed": False,
            "message": "Repair the project collaboration configuration before a guarded transition.",
            "actions": ["repair-collaboration-configuration"],
        }
    elif collaboration and role == "unknown":
        gate = {
            "code": "actor-not-enabled",
            "allowed": False,
            "message": f"Actor {actor} is not enabled for this project.",
            "actions": ["select-enabled-actor"],
        }
    elif intent in {"start-task", "prepare-commit"} and role == "worker":
        gate = {
            "code": "orchestrator-required",
            "allowed": False,
            "message": f"Intent {intent} is restricted to the project orchestrator.",
            "actions": ["handoff-to-orchestrator"],
        }
    elif intent == "start-project":
        if not environment["root_writable"] or not environment["git_available"]:
            gate = {
                "code": "environment-not-ready",
                "allowed": False,
                "message": "Resolve missing project-folder write access or Git availability before initialization.",
                "actions": ["fix-project-prerequisites"],
            }
        elif state in {"empty-directory", "empty-git-repository"}:
            gate = {
                "code": "project-intake-required",
                "allowed": False,
                "message": "Collect project description, technical choices, and task permissions before scaffolding.",
                "actions": ["complete-project-intake"],
            }
        else:
            gate = {
                "code": "take-over-required",
                "allowed": False,
                "message": "This directory is not empty; inspect and take over the existing project before initialization.",
                "actions": ["read-only-take-over", "review-merge-strategy"],
            }
    elif intent == "start-task":
        if state != "managed-project":
            gate = {
                "code": "project-memory-initialization-required",
                "allowed": False,
                "message": "Initialize or safely merge the project-memory documents before creating a task.",
                "actions": ["initialize-or-merge-project-memory"],
            }
        elif len(unresolved) > 1 and active is None:
            gate = {
                "code": "ambiguous-active-task",
                "allowed": False,
                "message": "Multiple unresolved tasks exist and STATUS does not identify one active task.",
                "actions": ["select-active-task", "repair-status"],
            }
        elif active is not None:
            gate = {
                "code": "resolve-active-task",
                "allowed": False,
                "message": f"Resolve active task {active['id']} ({active['status']}) before creating another task.",
                "actions": ["audit-and-close", "pause-and-switch", "continue-current-task"],
            }
    elif intent == "resume-task":
        if active is None:
            gate = {
                "code": "active-task-required",
                "allowed": False,
                "message": "No active task exists to resume.",
                "actions": ["ask-orchestrator-to-start-task"],
            }
        elif coordination is None:
            gate = {
                "code": "v4-coordination-required",
                "allowed": False,
                "message": "This task has no v4 coordination record; use the legacy workflow or migrate it explicitly.",
                "actions": ["migrate-task-coordination"],
            }
        elif coordination_problems:
            gate = {
                "code": "coordination-invalid",
                "allowed": False,
                "message": "Repair task coordination before resuming work.",
                "actions": ["repair-task-coordination"],
            }
        elif coordination.get("active_agent") != actor:
            gate = {
                "code": "non-active-agent",
                "allowed": False,
                "message": f"Task is controlled by {coordination.get('active_agent')}; {actor} cannot resume it.",
                "actions": ["request-formal-handoff"],
            }
        elif coordination.get("handoff_to") == actor:
            current = handoff_fingerprint(root)
            stale = current != coordination.get("handoff_fingerprint")
            gate = {
                "code": "handoff-snapshot-changed" if stale else "handoff-acceptance-required",
                "allowed": False,
                "message": (
                    "The project changed after handoff; return to the sender for reconciliation."
                    if stale
                    else "Accept the pending handoff before modifying controlled files."
                ),
                "actions": ["reconcile-handoff"] if stale else ["accept-handoff"],
            }
        else:
            gate = {
                "code": "none",
                "allowed": True,
                "message": f"Actor {actor} may resume task {active['id']} in phase {coordination.get('phase')}.",
                "actions": [],
            }
    elif intent == "prepare-commit":
        commit_task = active
        if commit_task is None and recent is not None and recent["status"] in {"DONE", "READY_FOR_REVIEW"}:
            commit_task = recent
        if not git["is_repository"]:
            gate = {
                "code": "project-git-required",
                "allowed": False,
                "message": "The project root is not its own Git repository.",
                "actions": ["initialize-or-select-project-repository"],
            }
        elif git["worktree"] == "clean":
            gate = {
                "code": "no-changes-to-commit",
                "allowed": False,
                "message": "The Git worktree is clean.",
                "actions": ["verify-target-repository"],
            }
        elif commit_task is None:
            gate = {
                "code": "active-task-required",
                "allowed": False,
                "message": "A current task packet is required before preparing a commit.",
                "actions": ["create-or-identify-task"],
            }
        elif commit_task["permissions"]["permission_git_commit"] != "allow":
            gate = {
                "code": "commit-not-authorized",
                "allowed": False,
                "message": "The active task does not authorize creating a Git commit.",
                "actions": ["obtain-explicit-commit-authorization", "update-current-task-permissions"],
            }
        elif commit_task["audit"]["status"] != "PASSED":
            gate = {
                "code": "task-audit-required" if commit_task["audit"]["status"] == "NOT_RUN" else "task-audit-stale",
                "allowed": False,
                "message": "Run and record a current task audit before preparing the commit.",
                "actions": ["run-audit", "record-audit"],
            }
    elif intent == "handoff":
        if active is None:
            gate = {
                "code": "no-active-task",
                "allowed": True,
                "message": "No active task is declared; hand off the project snapshot only.",
                "actions": ["audit-project-snapshot"],
            }
        elif coordination is not None:
            if coordination_problems:
                gate = {
                    "code": "coordination-invalid",
                    "allowed": False,
                    "message": "Repair task coordination before handoff.",
                    "actions": ["repair-task-coordination"],
                }
            elif coordination.get("active_agent") != actor:
                gate = {
                    "code": "non-active-agent",
                    "allowed": False,
                    "message": f"Only active actor {coordination.get('active_agent')} may hand off this task.",
                    "actions": ["request-formal-handoff"],
                }
            elif coordination.get("handoff_to"):
                gate = {
                    "code": "handoff-already-pending",
                    "allowed": False,
                    "message": f"Handoff already awaits {coordination.get('handoff_to')} acceptance.",
                    "actions": ["accept-or-reconcile-handoff"],
                }
            else:
                gate = {
                    "code": "none",
                    "allowed": True,
                    "message": "The active actor may create a formal handoff.",
                    "actions": [],
                }
        else:
            gate = {
                "code": "record-handoff",
                "allowed": False,
                "message": "Update the active task result and STATUS before handing off.",
                "actions": ["update-result", "update-status", "audit-handoff"],
            }
    else:
        raise ValueError(f"unknown workflow intent: {intent}")

    return {
        "schema": 2,
        "intent": intent,
        "actor": {"id": actor, "role": role},
        "project_state": state,
        "environment": environment,
        "git": git,
        "memory": {
            "initialized": state == "managed-project",
            "agents_managed": agents_managed,
        },
        "collaboration": collaboration,
        "coordination": coordination,
        "active_task": active,
        "recent_task": recent,
        "active_task_inferred": inferred,
        "unresolved_tasks": unresolved,
        "gate": gate,
    }


def write_status_for_started_task(root: Path, task_id: str, title: str) -> None:
    path = root / "docs" / "STATUS.md"
    text = path.read_text(encoding="utf-8")
    text = frontmatter_updates(
        text,
        {
            "updated": today_iso(),
            "source_commit": git_head(root, short=True),
            "active_task": task_id,
        },
    )
    text = replace_markdown_section(text, "Active work", f"- Task: `{task_id}`\n- Objective: {title}")
    text = replace_markdown_section(text, "Next action", "1. Complete the active task brief before implementation.")
    atomic_write(path, text)


def write_status_for_closed_task(root: Path, task_id: str, status: str, next_action: str) -> None:
    path = root / "docs" / "STATUS.md"
    text = path.read_text(encoding="utf-8")
    text = frontmatter_updates(
        text,
        {
            "updated": today_iso(),
            "source_commit": git_head(root, short=True),
            "active_task": "none",
            "last_task": task_id,
        },
    )
    text = replace_markdown_section(
        text,
        "Active work",
        f"- Task: none\n- Most recently closed: `{task_id}` ({status})",
    )
    text = replace_markdown_section(text, "Next action", f"1. {next_action}")
    atomic_write(path, text)
