#!/usr/bin/env python3
"""Analyze a Claude Code tool-event log (JSONL) and write a Markdown diagnostic report.

Usage:
    python analyzer.py [LOG] [-o REPORT]

LOG defaults to <project>/.claude/error-tracker/events.jsonl and REPORT to report.md
next to it. Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXCEPTION_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception))\b")
TIMEOUT_RE = re.compile(r"timed?\s*out|timeout|ETIMEDOUT|deadline exceeded", re.I)
EXIT_CODE_RE = re.compile(r"^Exit code (\d+)")
# Signals in a *successful* tool output that hint at a hidden failure.
SUSPECT_RE = re.compile(r"Traceback \(most recent call last\)|\bFAILED\b|\bfatal:|"
                        + EXCEPTION_RE.pattern + "|" + TIMEOUT_RE.pattern, re.I)

# Only well-known meanings of an error *type*; anything else gets no hint (no invented diagnoses).
HINTS = {
    "ModuleNotFoundError": "A Python module is not importable: missing dependency, wrong virtualenv, or wrong working directory / PYTHONPATH.",
    "ImportError": "A module was found but a name could not be imported: version mismatch or circular import.",
    "FileNotFoundError": "A path referenced by the command does not exist relative to the working directory.",
    "PermissionError": "The process lacks permission on a file or directory.",
    "SyntaxError": "The code being run (or a generated file) has a syntax error.",
    "Timeout": "The operation exceeded its time limit: slow or unreachable service, or a command waiting for input.",
    "Interrupted": "The tool call was aborted before completing.",
}


def default_log_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(root) / ".claude" / "error-tracker" / "events.jsonl"


def load_events(path: Path) -> tuple[list[dict], int]:
    """Return (events, number_of_malformed_lines). Missing file -> FileNotFoundError."""
    events, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(ev, dict) and ev.get("tool"):
                events.append(ev)
            else:
                bad += 1
    return events, bad


def dedupe(events: list[dict]) -> list[dict]:
    """One entry per tool_use_id; a failure record wins over a success record for the same call."""
    pos: dict[str, int] = {}
    out: list[dict] = []
    for ev in events:
        uid = ev.get("tool_use_id")
        if not uid or uid not in pos:
            if uid:
                pos[uid] = len(out)
            out.append(ev)
        elif not ev.get("ok", True) and out[pos[uid]].get("ok", True):
            out[pos[uid]] = ev
    return out


def signature(ev: dict) -> str:
    """Group key for a failure. Similar errors (same exception type, timeouts, exit codes) share it."""
    text = ev.get("error") or ev.get("output_tail") or ""
    prefix = "MCP " if str(ev.get("tool", "")).startswith("mcp__") else ""
    if ev.get("is_interrupt"):
        return "Interrupted"
    names = EXCEPTION_RE.findall(text)
    if names:
        return names[-1]  # the last exception in a traceback is the root cause
    if TIMEOUT_RE.search(text):
        return prefix + "Timeout"
    m = EXIT_CODE_RE.match(text)
    if m:
        return f"Exit code {m.group(1)}"
    first = next((l.strip() for l in text.splitlines() if l.strip()), "Unknown error")
    return prefix + re.sub(r"\d+", "N", first)[:80]


def first_detail(ev: dict) -> str:
    """Most informative single line of the error text (the exception line if any)."""
    text = ev.get("error") or ev.get("output_tail") or ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for l in reversed(lines):
        if EXCEPTION_RE.search(l) or TIMEOUT_RE.search(l):
            return l[:200]
    return lines[0][:200] if lines else ""


def analyze(events: list[dict]) -> dict:
    events = dedupe(events)
    failures = [e for e in events if not e.get("ok", True)]
    suspected = [e for e in events if e.get("ok", True) and SUSPECT_RE.search(e.get("output_tail") or "")]

    groups: dict[str, list[dict]] = defaultdict(list)
    for e in failures:
        groups[signature(e)].append(e)

    tool_total = Counter(e["tool"] for e in events)
    tool_fail = Counter(e["tool"] for e in failures)
    total = len(events)
    return {
        "total": total,
        "failures": len(failures),
        "failure_rate": (len(failures) / total * 100) if total else 0.0,
        "groups": sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])),
        "suspected": suspected,
        "tools": sorted(((t, tool_total[t], tool_fail[t]) for t in tool_total), key=lambda x: (-x[2], -x[1], x[0])),
        "sessions": len({e.get("session_id") for e in events if e.get("session_id")}),
    }


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render(stats: dict, log_path: str = "", malformed: int = 0) -> str:
    out = ["# Agent Error Tracker Report", ""]
    if log_path:
        out.append(f"Source: `{log_path}`  ")
    out += [
        f"Sessions: {stats['sessions']}", "",
        "## Summary", "",
        "| Metric | Value |", "|---|---|",
        f"| Operations observed | {stats['total']} |",
        f"| Failures (certain) | {stats['failures']} |",
        f"| Failure rate | {stats['failure_rate']:.0f}% |",
        f"| Suspected failures | {len(stats['suspected'])} |",
        "",
    ]
    if malformed:
        out += [f"> {malformed} malformed log line(s) were skipped.", ""]

    out += ["## Recurring errors", ""]
    if not stats["groups"]:
        out += ["No failures recorded.", ""]
    else:
        out += ["| Error | Occurrences | Tools |", "|---|---|---|"]
        for sig, evs in stats["groups"]:
            tools = ", ".join(sorted({e["tool"] for e in evs}))
            out.append(f"| {_cell(sig)} | {len(evs)} | {_cell(tools)} |")
        out.append("")
        for sig, evs in stats["groups"]:
            out += [f"### {sig} ({len(evs)})", ""]
            details = list(dict.fromkeys(d for d in (first_detail(e) for e in evs) if d))
            targets = list(dict.fromkeys(e.get("target") for e in evs if e.get("target")))
            if details:
                out.append("- Messages: " + "; ".join(f"`{_cell(d)}`" for d in details[:3]))
            if targets:
                out.append("- Operations: " + "; ".join(f"`{_cell(t)}`" for t in targets[:3]))
            times = sorted(e["ts"] for e in evs if e.get("ts"))
            if times:
                out.append(f"- First seen: {times[0]} - last seen: {times[-1]}")
            hint = HINTS.get(sig.removeprefix("MCP "))
            out.append(f"- Typical cause: {hint}" if hint else "- Typical cause: not enough information; inspect the messages above.")
            out.append("")

    out += ["## Tools involved", "", "| Tool | Operations | Failures |", "|---|---|---|"]
    out += [f"| {_cell(t)} | {n} | {f} |" for t, n, f in stats["tools"]]
    out.append("")

    if stats["suspected"]:
        out += ["## Suspected failures", "",
                "The tool reported success, but its output contains error-like text. Verify manually.", ""]
        for e in stats["suspected"][:10]:
            out.append(f"- `{_cell(e['tool'])}` `{_cell(e.get('target', ''))}`: `{_cell(first_detail(e))}`")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("log", nargs="?", type=Path, default=None, help="events JSONL file")
    p.add_argument("-o", "--output", type=Path, default=None, help="report path (default: report.md next to the log)")
    args = p.parse_args(argv)

    log = args.log or default_log_path()
    try:
        events, bad = load_events(log)
    except FileNotFoundError:
        print(f"No event log found at {log}. Are the hooks installed? Run a Claude Code session first.", file=sys.stderr)
        return 1
    stats = analyze(events)
    report = render(stats, str(log), bad)
    out = args.output or log.with_name("report.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written to {out}")
    print(f"Operations: {stats['total']}  Failures: {stats['failures']}  "
          f"Failure rate: {stats['failure_rate']:.0f}%  Suspected: {len(stats['suspected'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
