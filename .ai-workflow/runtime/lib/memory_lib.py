#!/usr/bin/env python3
"""Shared parsing, safety, and managed-guardrail helpers."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
REFERENCES = SKILL_ROOT / "references"
LESSONS_INDEX = REFERENCES / "lessons-index.md"
LESSONS_CANDIDATES = REFERENCES / "lessons-candidates.md"
WORKFLOW_GUARDRAILS = REFERENCES / "workflow-guardrails.md"
LESSON_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
CATEGORIES = {
    "architecture",
    "code-editing",
    "documentation",
    "git",
    "operations",
    "security",
    "testing",
}
CATEGORY_FILES = {
    category: REFERENCES / f"lessons-{category}.md" for category in CATEGORIES
}
MANAGED_START = "<!-- project-memory:managed:start -->"
MANAGED_END = "<!-- project-memory:managed:end -->"
PROFILE_RE = re.compile(r"<!-- project-memory:profile:([0-9a-f]{12}) -->")
CATEGORIES_RE = re.compile(r"<!-- project-memory:categories:([^>]+) -->")
PRIVATE_IP = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:Users|Documents and Settings|ProgramData)\\", re.IGNORECASE)
PRIVATE_UNIX_PATH = re.compile(r"(?<!<)/(?:home|Users|srv|opt|var/www)/[^\s`]+")
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?:[\"']?(?:password|passwd|token|secret|api[_-]?key)[\"']?|密码(?:为)?|密钥|令牌)"
    r"\s*[:=：]\s*(\"[^\"\r\n]*\"|'[^'\r\n]*'|`[^`\r\n]*`|[^\s|,;]+)"
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def metadata_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?im)^{re.escape(key)}:\s*[\"']?([^\n\"']+)", text)
    return match.group(1).strip() if match else None


def markdown_title(text: str) -> str | None:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return match.group(1).strip() if match else None


def markdown_section(text: str, heading: str) -> str | None:
    match = re.search(
        rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)", text
    )
    if not match:
        return None
    value = match.group(1).strip()
    value = re.sub(r"(?s)<!--.*?-->", "", value).strip()
    if value.startswith("Do not include credentials"):
        return None
    return value or None


def sensitive_findings(text: str) -> list[str]:
    findings: list[str] = []
    safe_fragments = (
        "<", "${", "$(", "***", "redacted", "placeholder", "example", "changeme",
        "not-configured", "none", "未配置", "替换", "环境变量",
    )
    for number, line in enumerate(text.splitlines(), start=1):
        match = CREDENTIAL_ASSIGNMENT.search(line)
        if match:
            value = match.group(1).strip("\"'`").lower()
            if not any(
                fragment.lower() in value or fragment.lower() in line.lower()
                for fragment in safe_fragments
            ):
                findings.append(f"credential-like assignment at line {number}")
        if PRIVATE_IP.search(line):
            findings.append(f"private IP address at line {number}")
        if EMAIL.search(line):
            findings.append(f"email address at line {number}")
        if WINDOWS_PATH.search(line) or PRIVATE_UNIX_PATH.search(line):
            findings.append(f"machine-specific absolute path at line {number}")
    return findings


def parse_active_rules(index_text: str | None = None) -> list[dict[str, str]]:
    text = index_text if index_text is not None else read_text(LESSONS_INDEX)
    rules: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\|\s*([A-Z][A-Z0-9-]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", line)
        if not match:
            continue
        lesson_id, summary, category = match.groups()
        if lesson_id == "ID" or lesson_id in seen:
            continue
        normalized_category = re.sub(r"[\s_]+", "-", category.strip().lower())
        if normalized_category not in CATEGORIES:
            raise ValueError(f"unknown category in lessons index for {lesson_id}: {category}")
        if not LESSON_ID.fullmatch(lesson_id):
            raise ValueError(f"invalid lesson ID in index: {lesson_id}")
        rules.append(
            {
                "id": lesson_id,
                "summary": summary.strip(),
                "category": normalized_category,
                "kind": "lesson",
            }
        )
        seen.add(lesson_id)
    if not rules:
        raise ValueError("lessons index contains no active rules")
    return rules


def parse_workflow_guardrails(text: str | None = None) -> list[dict[str, str]]:
    source = text if text is not None else read_text(WORKFLOW_GUARDRAILS)
    rules: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in source.splitlines():
        match = re.match(r"^\|\s*(FLOW-[0-9]+)\s*\|\s*(.*?)\s*\|\s*$", line)
        if not match:
            continue
        rule_id, summary = match.groups()
        if rule_id in seen:
            raise ValueError(f"duplicate workflow guardrail ID: {rule_id}")
        summary = summary.strip()
        if not summary:
            raise ValueError(f"workflow guardrail cannot be empty: {rule_id}")
        rules.append(
            {
                "id": rule_id,
                "summary": summary,
                "category": "workflow",
                "kind": "workflow",
            }
        )
        seen.add(rule_id)
    if not rules:
        raise ValueError("workflow guardrails contain no active rules")
    return rules


def filter_rules(rules: list[dict[str, str]], categories: set[str] | None) -> list[dict[str, str]]:
    if categories is None:
        return rules
    unknown = categories - CATEGORIES
    if unknown:
        raise ValueError("unknown categories: " + ", ".join(sorted(unknown)))
    filtered = [rule for rule in rules if rule["category"] in categories]
    if not filtered:
        raise ValueError("selected categories contain no active rules")
    return filtered


def parse_managed_rules(categories: set[str] | None) -> list[dict[str, str]]:
    return parse_workflow_guardrails() + filter_rules(parse_active_rules(), categories)


def rules_profile(rules: list[dict[str, str]]) -> str:
    canonical = "\n".join(
        f"{rule['kind']}\t{rule['id']}\t{rule['summary']}\t{rule['category']}"
        for rule in rules
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def categories_label(categories: set[str] | None) -> str:
    return "all" if categories is None else ",".join(sorted(categories))


def render_managed_content(
    rules: list[dict[str, str]], categories: set[str] | None, newline: str = "\n"
) -> str:
    lines = [
        f"<!-- project-memory:profile:{rules_profile(rules)} -->",
        f"<!-- project-memory:categories:{categories_label(categories)} -->",
    ]
    workflow = [rule for rule in rules if rule["kind"] == "workflow"]
    lessons = [rule for rule in rules if rule["kind"] == "lesson"]
    if workflow:
        lines.extend(("", "Core workflow guardrails:"))
        lines.extend(f"- {rule['summary']} `[{rule['id']}]`" for rule in workflow)
    if lessons:
        lines.extend(("", "Approved cross-project lessons:"))
        lines.extend(f"- {rule['summary']} `[{rule['id']}]`" for rule in lessons)
    return newline.join(lines)


def managed_categories(agents_text: str) -> set[str] | None:
    match = CATEGORIES_RE.search(agents_text)
    if not match or match.group(1).strip().lower() == "all":
        return None
    categories = {part.strip().lower() for part in match.group(1).split(",") if part.strip()}
    unknown = categories - CATEGORIES
    if unknown:
        raise ValueError("AGENTS managed block has unknown categories: " + ", ".join(sorted(unknown)))
    return categories


def managed_profile(agents_text: str) -> str | None:
    match = PROFILE_RE.search(agents_text)
    return match.group(1) if match else None


def replace_managed_block(
    agents_text: str, rules: list[dict[str, str]], categories: set[str] | None
) -> str:
    if agents_text.count(MANAGED_START) != 1 or agents_text.count(MANAGED_END) != 1:
        raise ValueError("AGENTS.md must contain exactly one managed start/end marker pair")
    newline = "\r\n" if "\r\n" in agents_text else "\n"
    replacement = newline.join(
        (
            MANAGED_START,
            render_managed_content(rules, categories, newline),
            MANAGED_END,
        )
    )
    pattern = re.compile(
        re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END), re.DOTALL
    )
    return pattern.sub(lambda _: replacement, agents_text, count=1)


def first_summary(text: str, limit: int = 180) -> str:
    line = next((item.strip() for item in text.splitlines() if item.strip()), "")
    line = re.sub(r"^[-*]\s+", "", line)
    line = re.sub(r"\s+", " ", line).replace("|", "/")
    if not line:
        raise ValueError("guardrail cannot be empty")
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
