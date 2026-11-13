#!/usr/bin/env python3
"""Claude Code hook: append one compact, redacted record per tool call to a JSONL log.

Register it for the PostToolUse and PostToolUseFailure events. It reads the hook
payload from stdin, never blocks Claude Code, and always exits 0.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from analyzer import SUSPECT_RE

MAX_TARGET = 200
MAX_TEXT = 2000

SECRET_PATTERNS = [  # order matters: Bearer first, so "Authorization: Bearer x" loses the token itself
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password|passwd|pwd|authorization)(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(--?(?:password|passwd|token|api-key|secret))(\s+|=)\S+"), r"\1\2[REDACTED]"),
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://[REDACTED]@"),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,})"), "[REDACTED]"),
]
FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit"}


def redact(text: str) -> str:
    for pattern, repl in SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def clip(text: str, limit: int = MAX_TEXT) -> str:
    """Keep the first line (e.g. 'Exit code 1') and the tail, where the root cause usually is."""
    if len(text) <= limit:
        return text
    first = text.split("\n", 1)[0][:200]
    return f"{first}\n...\n{text[-(limit - len(first) - 5):]}"


def target_of(tool: str, tool_input: dict) -> str:
    """Short, non-sensitive description of what the tool acted on. File contents are never stored."""
    if tool in ("Bash", "PowerShell"):
        return redact(str(tool_input.get("command", "")))[:MAX_TARGET]
    if tool in FILE_TOOLS:
        return str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")[:MAX_TARGET]
    if tool in ("Glob", "Grep"):
        return redact(str(tool_input.get("pattern", "")))[:MAX_TARGET]
    if tool == "WebFetch" and tool_input.get("url"):
        u = urlsplit(str(tool_input["url"]))  # drop query/fragment: they often carry tokens
        return f"{u.scheme}://{u.hostname or ''}{u.path}"[:MAX_TARGET]
    return tool


def build_record(payload: dict) -> dict:
    tool = str(payload.get("tool_name") or "unknown")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    failed = payload.get("hook_event_name") == "PostToolUseFailure"
    rec = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": payload.get("session_id"),
        "event": payload.get("hook_event_name"),
        "tool": tool,
        "tool_use_id": payload.get("tool_use_id"),
        "target": target_of(tool, tool_input),
        "ok": not failed,
        "duration_ms": payload.get("duration_ms"),
    }
    if failed:
        rec["error"] = clip(redact(str(payload.get("error") or "")))
        rec["is_interrupt"] = bool(payload.get("is_interrupt"))
    else:
        resp = payload.get("tool_response")
        # Successful shell commands can still print errors: keep the tail for "suspected" analysis.
        # Claude Code may merge stderr into stdout, so stdout is kept too, but only when it looks like an error.
        if isinstance(resp, dict):
            out, err = str(resp.get("stdout") or ""), str(resp.get("stderr") or "")
            text = "\n".join(p for p in (out if SUSPECT_RE.search(out) else "", err) if p)
            if text:
                rec["output_tail"] = clip(redact(text), 500)
    return rec


def log_path(payload: dict) -> Path:
    if os.environ.get("AGENT_ERROR_TRACKER_LOG"):
        return Path(os.environ["AGENT_ERROR_TRACKER_LOG"])
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return Path(root) / ".claude" / "error-tracker" / "events.jsonl"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
        if not isinstance(payload, dict) or payload.get("hook_event_name") not in ("PostToolUse", "PostToolUseFailure"):
            return 0
        path = log_path(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(build_record(payload), ensure_ascii=False) + "\n")
    except Exception as exc:  # never interfere with Claude Code: report on stderr (debug log only) and exit 0
        print(f"agent-error-tracker: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
