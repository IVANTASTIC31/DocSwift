#!/usr/bin/env python3
"""Shared v4 collaboration, actor, handoff, and adapter-state helpers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from memory_lib import atomic_write


RUNTIME_VERSION = "4.0.0"
SUPPORTED_ORCHESTRATORS = {"codex"}
SUPPORTED_WORKERS = {"claude-code", "hermes", "opencode"}
COLLABORATION_RELATIVE = Path(".ai-workflow/collaboration.json")
COLLABORATION_MANAGED_START = "<!-- project-memory:collaboration:start -->"
COLLABORATION_MANAGED_END = "<!-- project-memory:collaboration:end -->"


def collaboration_path(root: Path) -> Path:
    return root / COLLABORATION_RELATIVE


def coordination_path(root: Path, task_id: str) -> Path:
    return root / ".ai-workflow" / "tasks" / task_id / "coordination.json"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_collaboration(root: Path) -> dict[str, Any] | None:
    return load_json(collaboration_path(root))


def load_coordination(root: Path, task_id: str) -> dict[str, Any] | None:
    return load_json(coordination_path(root, task_id))


def validate_collaboration(value: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if value.get("schema") != 1:
        problems.append("collaboration.schema must be 1")
    if value.get("runtime_version") != RUNTIME_VERSION:
        problems.append(
            f"collaboration.runtime_version must be {RUNTIME_VERSION}; got {value.get('runtime_version')}"
        )
    if value.get("orchestrator") not in SUPPORTED_ORCHESTRATORS:
        problems.append("collaboration.orchestrator must be codex")
    workers = value.get("enabled_workers")
    if not isinstance(workers, list) or not workers:
        problems.append("collaboration.enabled_workers must be a non-empty list")
    elif any(worker not in SUPPORTED_WORKERS for worker in workers):
        problems.append("collaboration.enabled_workers contains an unsupported agent")
    elif len(workers) != len(set(workers)):
        problems.append("collaboration.enabled_workers contains duplicates")
    if value.get("role_policy") != "orchestrator-worker":
        problems.append("collaboration.role_policy must be orchestrator-worker")
    if value.get("single_active_worker") is not True:
        problems.append("collaboration.single_active_worker must be true")
    return problems


def actor_role(root: Path, actor: str) -> str:
    collaboration = load_collaboration(root)
    if collaboration is None:
        return "legacy-orchestrator" if actor == "codex" else "unknown"
    problems = validate_collaboration(collaboration)
    if problems:
        raise ValueError("invalid collaboration configuration: " + "; ".join(problems))
    if actor == collaboration["orchestrator"]:
        return "orchestrator"
    if actor in collaboration["enabled_workers"]:
        return "worker"
    return "unknown"


def require_orchestrator(root: Path, actor: str, operation: str) -> None:
    role = actor_role(root, actor)
    if role not in {"orchestrator", "legacy-orchestrator"}:
        raise ValueError(f"{operation} is restricted to the orchestrator; actor={actor}, role={role}")


def require_enabled_worker(root: Path, worker: str) -> None:
    collaboration = load_collaboration(root)
    if collaboration is None:
        raise ValueError("project collaboration is not configured")
    if worker not in collaboration.get("enabled_workers", []):
        raise ValueError(f"worker is not enabled for this project: {worker}")


def validate_coordination(value: dict[str, Any], task_id: str | None = None) -> list[str]:
    problems: list[str] = []
    expected = task_id or value.get("task_id")
    if value.get("task_id") != expected:
        problems.append("coordination.task_id does not match its task directory")
    if value.get("orchestrator") != "codex":
        problems.append("coordination.orchestrator must be codex")
    if value.get("execution_agent") not in SUPPORTED_WORKERS:
        problems.append("coordination.execution_agent is unsupported")
    valid_agents = {value.get("orchestrator"), value.get("execution_agent")}
    if value.get("active_agent") not in valid_agents:
        problems.append("coordination.active_agent is outside the task's actor pair")
    if not isinstance(value.get("phase"), str) or not value.get("phase"):
        problems.append("coordination.phase is required")
    return problems


def _iter_handoff_paths(root: Path) -> list[Path]:
    excluded_dirs = {
        ".git", ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".venv", "__pycache__", "build", "coverage", "dist", "node_modules",
        "target", "venv",
    }
    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in excluded_dirs for part in relative.parts):
            continue
        if relative.name == "coordination.json" and ".ai-workflow" in relative.parts:
            continue
        result.append(relative)
    return sorted(result, key=lambda item: item.as_posix())


def handoff_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in _iter_handoff_paths(root):
        path = root / relative
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"<symlink>")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        else:
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _protected_paths(root: Path, task_id: str) -> list[Path]:
    candidates = [
        Path("AGENTS.md"), Path("CHANGELOG.md"), Path("docs/STATUS.md"),
        Path("docs/ARCHITECTURE.md"),
        Path(f".ai-workflow/tasks/{task_id}/brief.md"),
    ]
    for directory in ("docs/adr", "docs/runbooks", "docs/lessons"):
        base = root / directory
        if base.is_dir():
            candidates.extend(path.relative_to(root) for path in base.rglob("*.md"))
    return sorted({path for path in candidates if (root / path).is_file()}, key=lambda p: p.as_posix())


def protected_document_hashes(root: Path, task_id: str) -> dict[str, str]:
    return {
        relative.as_posix(): hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in _protected_paths(root, task_id)
    }


def protected_document_drift(root: Path, task_id: str, recorded: dict[str, str]) -> list[str]:
    current = protected_document_hashes(root, task_id)
    return sorted(
        path for path in set(recorded) | set(current) if recorded.get(path) != current.get(path)
    )
