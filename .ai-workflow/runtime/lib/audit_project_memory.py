#!/usr/bin/env python3
"""Read-only audit for project-memory structure, task identity, and doc impact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from memory_lib import (
    MANAGED_END,
    MANAGED_START,
    managed_categories,
    managed_profile,
    parse_managed_rules,
    rules_profile,
)
from workflow_lib import PERMISSION_DEFAULTS, PERMISSION_TARGET_DEFAULTS
from collaboration_lib import (
    COLLABORATION_MANAGED_END,
    COLLABORATION_MANAGED_START,
    RUNTIME_VERSION,
    load_collaboration,
    validate_collaboration,
    validate_coordination,
)


CORE_REQUIRED = ("AGENTS.md", "docs/STATUS.md", "docs/ARCHITECTURE.md")
TASK_STATES = {
    "PLANNED",
    "IN_PROGRESS",
    "PAUSED",
    "BLOCKED",
    "READY_FOR_REVIEW",
    "DONE",
    "ABANDONED",
}
EXCLUDED_PARTS = {".git", ".skill-build", ".skill-test", "node_modules", "target", "dist", "uploads"}
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?:[\"']?(?:password|passwd|token|secret|api[_-]?key)[\"']?|密码(?:为)?|密钥|令牌)"
    r"\s*[:=：]\s*(\"[^\"\r\n]*\"|'[^'\r\n]*'|`[^`\r\n]*`|[^\s|,;]+)"
)


def git(root: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
        return result.returncode, result.stdout.rstrip("\r\n")
    except OSError as exc:
        return 127, str(exc)


def metadata_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?im)^{re.escape(key)}:\s*[\"']?([^\n\"']+)", text)
    return match.group(1).strip() if match else None


def task_status(text: str) -> str | None:
    value = metadata_value(text, "status")
    return value.upper() if value else None


def changed_file_advice(paths: list[str], changelog_exists: bool) -> list[str]:
    advice: set[str] = set()
    user_visible = False
    for raw in paths:
        path = raw.replace("\\", "/").lower()
        if any(token in path for token in ("migration", "schema", "entity", "dto", "/api/", "controller")):
            advice.add("Review ARCHITECTURE and ADR impact: data model or interface files changed.")
        operational = (
            path.startswith("deploy/")
            or "/deploy/" in path
            or any(
                token in path
                for token in (
                    "dockerfile", "docker-compose", "nginx", "systemd",
                    ".github/workflows", "application-prod",
                )
            )
        )
        if operational:
            advice.add("Review runbook and deployment-topology impact: deployment artifacts changed.")
        if any(token in path for token in ("/views/", "/components/", "pages/", "routes/", "router/")):
            user_visible = True
            advice.add("Review CHANGELOG impact: user-visible UI or routing files changed.")
        if path.startswith("docs/") or path == "agents.md" or path == "changelog.md":
            advice.add("Confirm documentation edits have one canonical owner and no stale duplicated values.")
    if user_visible and not changelog_exists:
        advice.add("CHANGELOG is absent; create one only if this project publishes user-visible releases.")
    if paths:
        advice.add("Update the active task result; update STATUS only if current state, risk, blocker, or next action changed.")
    return sorted(advice)


def markdown_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for top in ("README.md", "AGENTS.md", "CHANGELOG.md"):
        path = root / top
        if path.is_file():
            candidates.append(path)
    for folder in (root / "docs", root / ".ai-workflow"):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.md"):
            if not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts):
                candidates.append(path)
    return sorted(set(candidates))


def possible_credentials(root: Path) -> list[str]:
    findings: list[str] = []
    safe_fragments = (
        "<", "${", "$(", "***", "redacted", "placeholder", "example", "changeme",
        "not-configured", "none", "未配置", "替换", "环境变量",
    )
    for path in markdown_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            match = CREDENTIAL_ASSIGNMENT.search(line)
            if not match:
                continue
            value = match.group(1).strip("\"'`").lower()
            if any(fragment.lower() in value or fragment.lower() in line.lower() for fragment in safe_fragments):
                continue
            relative = path.relative_to(root).as_posix()
            findings.append(f"possible credential-like assignment: {relative}:{number}")
            if len(findings) >= 10:
                return findings
    return findings


def audit_packet(task_dir: Path, warnings: list[str]) -> None:
    brief = task_dir / "brief.md"
    result = task_dir / "result.md"
    if not brief.is_file() or not result.is_file():
        warnings.append(f"incomplete task packet: {task_dir.name}")
        return
    brief_text = brief.read_text(encoding="utf-8")
    result_text = result.read_text(encoding="utf-8")
    brief_id = metadata_value(brief_text, "task_id")
    result_id = metadata_value(result_text, "task_id")
    if brief_id != task_dir.name or result_id != task_dir.name:
        warnings.append(
            f"task identity mismatch in {task_dir.name}: brief={brief_id!r}, result={result_id!r}"
        )
    for filename, text, fields in (
        ("brief.md", brief_text, ("created", "updated", "base_commit")),
        ("result.md", result_text, ("updated", "base_commit", "last_verified")),
    ):
        for field in fields:
            if metadata_value(text, field) is None:
                warnings.append(f"{task_dir.name}/{filename} missing freshness field: {field}")
    current = task_status(result_text)
    if current and current not in TASK_STATES:
        warnings.append(f"unknown task result status in {task_dir.name}: {current}")
    permission_values = {
        "permission_file_edits": {"allow", "deny"},
        "permission_dependency_install": {"allow", "ask", "deny"},
        "permission_git_commit": {"allow", "deny"},
        "permission_git_push": {"allow", "deny"},
        "permission_local_database": {"allow", "deny"},
        "permission_deploy": {"allow", "deny"},
        "permission_external_mutation": {"allow", "deny"},
    }
    for field in PERMISSION_DEFAULTS:
        value = metadata_value(brief_text, field)
        if value is not None and value.lower() not in permission_values[field]:
            warnings.append(f"invalid task permission in {task_dir.name}/brief.md: {field}={value}")
    for field, default in PERMISSION_TARGET_DEFAULTS.items():
        value = metadata_value(brief_text, field)
        if value is not None and not value.strip():
            warnings.append(f"empty task permission target in {task_dir.name}/brief.md: {field}")
    scoped_permissions = (
        ("permission_git_push", "permission_git_push_target"),
        ("permission_deploy", "permission_deploy_target"),
        ("permission_external_mutation", "permission_external_scope"),
    )
    for permission_field, target_field in scoped_permissions:
        permission = (metadata_value(brief_text, permission_field) or "deny").lower()
        target = (metadata_value(brief_text, target_field) or "none").lower()
        if permission == "allow" and target == "none":
            warnings.append(
                f"allowed task permission lacks target in {task_dir.name}/brief.md: {target_field}"
            )
        if permission == "deny" and target != "none":
            warnings.append(
                f"denied task permission has a target in {task_dir.name}/brief.md: {target_field}"
            )
    audit_status = metadata_value(result_text, "audit_status")
    if audit_status and audit_status.upper() not in {"NOT_RUN", "PASSED", "STALE"}:
        warnings.append(f"invalid audit status in {task_dir.name}/result.md: {audit_status}")
    if audit_status and audit_status.upper() == "PASSED":
        for field in (
            "audited_at",
            "audited_by",
            "audited_commit",
            "audited_worktree_fingerprint",
        ):
            if not metadata_value(result_text, field):
                warnings.append(f"{task_dir.name}/result.md PASSED audit missing field: {field}")


def audit_legacy(root: Path, warnings: list[str]) -> None:
    legacy_root = root / ".ai-workflow"
    if not legacy_root.is_dir():
        return
    files = sorted(path for path in legacy_root.glob("*.md") if path.is_file())
    if not files:
        return
    warnings.append("legacy singleton task artifacts found: " + ", ".join(path.name for path in files))
    statuses: dict[str, str] = {}
    freshness_missing: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        status = task_status(text)
        if status:
            statuses[path.name] = status
        needs = ["updated"]
        if path.name != "task.md":
            needs.extend(("base_commit", "last_verified"))
        if any(metadata_value(text, field) is None for field in needs):
            freshness_missing.append(path.name)
    if len(set(statuses.values())) > 1:
        rendered = ", ".join(f"{name}={status}" for name, status in statuses.items())
        warnings.append("conflicting legacy task statuses: " + rendered)
    if freshness_missing:
        warnings.append("legacy artifacts lack stable freshness metadata: " + ", ".join(freshness_missing))


def audit_v4(root: Path, warnings: list[str], notices: list[str]) -> None:
    collaboration = load_collaboration(root)
    if collaboration is None:
        notices.append(
            "v4 project-local runtime is not configured; v2/v3 workflows remain usable and migration is optional"
        )
        return
    problems = validate_collaboration(collaboration)
    warnings.extend(f"invalid collaboration configuration: {problem}" for problem in problems)
    runtime = root / ".ai-workflow" / "runtime"
    manifest_path = runtime / "manifest.json"
    if not manifest_path.is_file():
        warnings.append("v4 runtime manifest is missing")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("runtime_version") != RUNTIME_VERSION:
                warnings.append(
                    f"runtime version is stale: {manifest.get('runtime_version')} != {RUNTIME_VERSION}"
                )
            if manifest.get("guardrail_profile") != collaboration.get("guardrail_profile"):
                warnings.append("runtime and collaboration guardrail profiles differ")
            for relative, expected in manifest.get("files", {}).items():
                path = runtime / relative
                actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
                if actual != expected:
                    warnings.append(
                        f"runtime integrity mismatch: {relative} expected={expected}, actual={actual}"
                    )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            warnings.append(f"runtime manifest is invalid: {exc}")

    required = [Path(".agents/skills/project-memory-runtime/SKILL.md")]
    workers = set(collaboration.get("enabled_workers", []))
    if "claude-code" in workers:
        required.extend((Path("CLAUDE.md"), Path(".claude/commands/maintain-project-memory.md")))
    if "opencode" in workers:
        required.append(Path(".opencode/commands/maintain-project-memory.md"))
    for relative in required:
        if not (root / relative).is_file():
            warnings.append(f"enabled Agent adapter is missing: {relative.as_posix()}")

    agents = root / "AGENTS.md"
    if agents.is_file():
        text = agents.read_text(encoding="utf-8")
        if text.count(COLLABORATION_MANAGED_START) != 1 or text.count(COLLABORATION_MANAGED_END) != 1:
            warnings.append("AGENTS collaboration managed marker pair is missing or ambiguous")

    tasks_root = root / ".ai-workflow" / "tasks"
    if tasks_root.is_dir():
        for task_dir in sorted(path for path in tasks_root.iterdir() if path.is_dir()):
            path = task_dir / "coordination.json"
            if not path.is_file():
                notices.append(f"legacy task has no v4 coordination record: {task_dir.name}")
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                for problem in validate_coordination(value, task_dir.name):
                    warnings.append(f"{task_dir.name}/coordination.json: {problem}")
                if value.get("execution_agent") not in workers:
                    warnings.append(
                        f"{task_dir.name}/coordination.json uses a disabled worker: {value.get('execution_agent')}"
                    )
                brief = task_dir / "brief.md"
                result = task_dir / "result.md"
                if brief.is_file():
                    brief_text = brief.read_text(encoding="utf-8")
                    if metadata_value(brief_text, "orchestrator_agent") != value.get("orchestrator"):
                        warnings.append(f"{task_dir.name}/brief.md orchestrator differs from coordination")
                    if metadata_value(brief_text, "execution_agent") != value.get("execution_agent"):
                        warnings.append(f"{task_dir.name}/brief.md execution Agent differs from coordination")
                if result.is_file():
                    result_text = result.read_text(encoding="utf-8")
                    if metadata_value(result_text, "execution_agent") != value.get("execution_agent"):
                        warnings.append(f"{task_dir.name}/result.md execution Agent differs from coordination")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                warnings.append(f"invalid coordination JSON for {task_dir.name}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--actor", default="codex")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")

    warnings: list[str] = []
    notices: list[str] = []
    for relative in CORE_REQUIRED:
        if not (root / relative).is_file():
            warnings.append(f"missing canonical document: {relative}")

    agents_path = root / "AGENTS.md"
    if agents_path.is_file():
        agents_text = agents_path.read_text(encoding="utf-8")
        if agents_text.count(MANAGED_START) != 1 or agents_text.count(MANAGED_END) != 1:
            warnings.append("AGENTS managed marker pair is missing or ambiguous")
        else:
            try:
                categories = managed_categories(agents_text)
                expected = rules_profile(parse_managed_rules(categories))
                actual = managed_profile(agents_text)
                if actual != expected:
                    warnings.append(
                        "AGENTS global guardrails are stale: "
                        f"current={actual or 'missing'}, expected={expected}; "
                        "run sync_project_agents.py"
                    )
            except ValueError as exc:
                warnings.append(f"AGENTS managed guardrail metadata is invalid: {exc}")

    audit_legacy(root, warnings)
    audit_v4(root, warnings, notices)

    tasks_root = root / ".ai-workflow" / "tasks"
    if tasks_root.is_dir():
        for task_dir in sorted(path for path in tasks_root.iterdir() if path.is_dir()):
            audit_packet(task_dir, warnings)

    status_path = root / "docs" / "STATUS.md"
    if status_path.is_file():
        status_text = status_path.read_text(encoding="utf-8")
        for key in ("updated", "source_commit", "last_verified"):
            if metadata_value(status_text, key) is None:
                warnings.append(f"STATUS missing freshness field: {key}")
        active_task = metadata_value(status_text, "active_task")
        if active_task and active_task.lower() not in {"none", "null", "n/a"}:
            if not (tasks_root / active_task).is_dir():
                warnings.append(f"STATUS points to missing active task packet: {active_task}")
        last_task = metadata_value(status_text, "last_task")
        if last_task and last_task.lower() not in {"none", "null", "n/a"}:
            if not (tasks_root / last_task).is_dir():
                warnings.append(f"STATUS points to missing last task packet: {last_task}")

    warnings.extend(possible_credentials(root))

    code, status = git(root, "status", "--short")
    if code == 0:
        print("GIT STATUS")
        print(status or "clean")
        changed = []
        for line in status.splitlines():
            if len(line) >= 4:
                path = line[3:]
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                changed.append(path)
        advice = changed_file_advice(changed, (root / "CHANGELOG.md").is_file())
    else:
        warnings.append("Git status unavailable; repository state is unverified")
        advice = []

    print("\nSTRUCTURE AND MEMORY INTEGRITY")
    if warnings:
        for warning in warnings:
            print(f"WARN    {warning}")
    else:
        print("OK      canonical files and task identities are structurally consistent")
    for notice in notices:
        print(f"NOTICE  {notice}")

    print("\nDOCUMENT IMPACT")
    if advice:
        for item in advice:
            print(f"REVIEW  {item}")
    else:
        print("OK      no changed-file documentation routing suggestions")

    print("\nNOTE    This audit is heuristic and read-only; verify facts and permissions before acting.")
    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
