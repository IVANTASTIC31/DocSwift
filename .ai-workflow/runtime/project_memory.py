#!/usr/bin/env python3
"""Portable command router for the pinned project-memory runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parent
LIB = RUNTIME_ROOT / "lib"
sys.path.insert(0, str(LIB))

COMMANDS = {
    "preflight": "workflow_preflight.py",
    "start-task": "start_task.py",
    "handoff": "handoff_task.py",
    "audit": "audit_project_memory.py",
    "record-audit": "record_task_audit.py",
    "close-task": "close_task.py",
    "propose-lesson": "propose_lesson.py",
}


def verify_runtime() -> list[str]:
    manifest = json.loads((RUNTIME_ROOT / "manifest.json").read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for relative, expected in manifest.get("files", {}).items():
        path = RUNTIME_ROOT / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        if actual != expected:
            mismatches.append(f"{relative}: expected={expected}, actual={actual}")
    return mismatches


def runtime_info(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Inspect and verify the project-local runtime.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--actor", default="codex")
    args = parser.parse_args(arguments)
    manifest_path = RUNTIME_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = verify_runtime()
    print(json.dumps({
        "runtime_version": manifest.get("runtime_version"),
        "guardrail_profile": manifest.get("guardrail_profile"),
        "actor": args.actor,
        "project_root": str(args.root.resolve()),
        "integrity": "PASSED" if not mismatches else "FAILED",
        "mismatches": mismatches,
    }, ensure_ascii=False, indent=2))
    return 0 if not mismatches else 1


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: project_memory.py <command> [arguments]", file=sys.stderr)
        return 2
    command = sys.argv[1]
    if command == "runtime-info":
        return runtime_info(sys.argv[2:])
    mismatches = verify_runtime()
    if mismatches:
        print("runtime integrity check failed:", file=sys.stderr)
        for mismatch in mismatches:
            print("- " + mismatch, file=sys.stderr)
        return 1
    script_name = COMMANDS.get(command)
    if script_name is None:
        print("unknown command: " + command, file=sys.stderr)
        return 2
    script = LIB / script_name
    if not script.is_file():
        print("runtime command is missing: " + script_name, file=sys.stderr)
        return 2
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
