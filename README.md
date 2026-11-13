# Agent Error Tracker

A small, dependency-free Python tool that records tool failures during [Claude Code](https://code.claude.com) sessions through the official hooks, groups recurring errors, and produces a Markdown diagnostic report. A Claude Code Skill (`/error-tracker`) runs the analysis and summarizes it in the chat.

- Standard library only (pytest for tests)
- Local only: no cloud services, no database, no network calls
- Never blocks or changes Claude Code behaviour (the hook always exits 0)
- Secrets are redacted before anything is written to disk

## How it works

```
Claude Code tool call
        │
        ├─ PostToolUse         ─┐
        └─ PostToolUseFailure  ─┴─► capture.py ──► .claude/error-tracker/events.jsonl
                                                          │
/error-tracker (Skill) ──► analyzer.py ◄──────────────────┘
                               │
                               └─► .claude/error-tracker/report.md ──► summary in chat
```

| File | Role |
|---|---|
| `.claude/skills/error-tracker/scripts/capture.py` | Hook. Reads the hook JSON from stdin, writes one compact, redacted record per tool call. |
| `.claude/skills/error-tracker/scripts/analyzer.py` | Loads the log, deduplicates, classifies and groups failures, renders the report. Also a CLI. |
| `.claude/skills/error-tracker/SKILL.md` | The `/error-tracker` Skill: runs the analyzer, reads the report, presents the results. |
| `.claude/settings.json` | Hook registration for this project. |
| `examples/` | A reproducible sample session and the report generated from it. |

Everything the tool needs lives in one folder (`.claude/skills/error-tracker/`), so installing it in another project means copying that folder and adding the hooks.

### Hook events used

According to the [hooks reference](https://code.claude.com/docs/en/hooks):

- **`PostToolUseFailure`**: fires when a tool call fails. It provides `tool_name`, `tool_input`, `tool_use_id`, `error`, `is_interrupt` and `duration_ms`. For Bash/PowerShell the `error` string starts with `Exit code N`.
- **`PostToolUse`**: fires when a tool call succeeds. It provides `tool_response`, which for Bash includes `stdout` and `stderr`.

### Event format

One JSON object per line:

```json
{"ts": "2026-11-12T10:00:01Z", "session_id": "…", "event": "PostToolUseFailure", "tool": "Bash",
 "tool_use_id": "toolu_01", "target": "pytest tests/", "ok": false,
 "error": "Exit code 2\n…ModuleNotFoundError: No module named 'requests'", "is_interrupt": false, "duration_ms": 1830}
```

| Field | Meaning |
|---|---|
| `target` | What the tool acted on: the shell command, the file path, the search pattern, the URL without its query string, or the tool name. File contents are never stored. |
| `ok` | `false` only for `PostToolUseFailure`, which marks a certain failure. |
| `error` | Redacted error text. Only the first line and the tail are kept, up to 2,000 characters. |
| `output_tail` | For successful shell commands only: the redacted tail of stderr. It is used to detect suspected failures. |

**Redaction**: Bearer tokens, `key=value` / `key: value` pairs for keys such as token, secret, password, api_key and authorization, `--password`-style flags, credentials in URLs, and well-known token formats (`sk-…`, `ghp_…`, `github_pat_…`, `AKIA…`, `xox…-`). This is pattern-based, so it is best effort. The log is git-ignored and stays on your machine.

### Analysis rules

- **Total operations**: unique `tool_use_id`s. If the same call is logged twice, it is counted once, and the failure record wins.
- **Certain failures**: events reported by the `PostToolUseFailure` hook.
- **Suspected failures**: calls that reported success but whose stderr contains a traceback, an `…Error`/`…Exception`, `FAILED`, `fatal:` or a timeout. They are listed separately and never counted in the failure rate.
- **Grouping**: failures are grouped by signature, using the first rule that matches:
  1. The interrupt flag gives `Interrupted`.
  2. Otherwise, the *last* exception name in the text, which is the root cause in a traceback. For example `ModuleNotFoundError`.
  3. Otherwise, timeout text gives `Timeout`, or `MCP Timeout` for `mcp__*` tools.
  4. Otherwise, `Exit code N`.
  5. Otherwise, the normalized first line of the error.
- **Typical causes** are shown only for well-known error types. For anything else the report says there is not enough information, instead of guessing.

## Installation

Requires Python 3.9+ and Claude Code.

**In this repository**: the hooks are already registered in `.claude/settings.json`. Open the folder with Claude Code and accept the project settings.

**In another project**:

1. Copy `.claude/skills/error-tracker/` into the other project's `.claude/skills/` folder.
2. Merge the `hooks` block from this repo's `.claude/settings.json` into that project's `.claude/settings.json`.
3. Add `.claude/error-tracker/` to its `.gitignore`.

**For all projects**:

1. Copy the folder to `~/.claude/skills/error-tracker/`.
2. Add the hooks to `~/.claude/settings.json`, with the command pointing to `~/.claude/skills/error-tracker/scripts/capture.py`.

> The hook command uses `python`. On macOS and on Linux distributions without a `python` alias, change it to `python3`.

Restart Claude Code after changing hooks, then check them with `/hooks`.

## Usage

Work normally in Claude Code; events are appended to `.claude/error-tracker/events.jsonl`. Then:

```
/error-tracker
```

Or run the analyzer directly:

```bash
python .claude/skills/error-tracker/scripts/analyzer.py                       # default project log
python .claude/skills/error-tracker/scripts/analyzer.py path/to/events.jsonl -o report.md
```

Set `AGENT_ERROR_TRACKER_LOG` to use a different log path, for both the hook and the analyzer.

## Demo in one minute

```bash
python .claude/skills/error-tracker/scripts/analyzer.py examples/sample-session.jsonl -o examples/sample-report.md
```

The sample session has six operations:

1. `pytest` fails with `ModuleNotFoundError`.
2. `pytest` fails again with the same error.
3. A file is read correctly.
4. An MCP tool times out.
5. `pytest` passes.
6. `git status` succeeds.

Output from [`examples/sample-report.md`](examples/sample-report.md):

```markdown
| Metric | Value |
|---|---|
| Operations observed | 6 |
| Failures (certain) | 3 |
| Failure rate | 50% |
| Suspected failures | 0 |

| Error | Occurrences | Tools |
|---|---|---|
| ModuleNotFoundError | 2 | Bash |
| MCP Timeout | 1 | mcp__docs__search |

### ModuleNotFoundError (2)

- Messages: `E   ModuleNotFoundError: No module named 'requests'`
- Operations: `pytest tests/`; `pytest tests/ -x`
- Typical cause: A Python module is not importable: missing dependency, wrong virtualenv, or wrong working directory / PYTHONPATH.
```

## Tests

```bash
pip install pytest
python -m pytest
```

The tests cover:

- the expected statistics for the sample session
- error classification and grouping
- deduplication
- suspected failures versus certain failures
- malformed and missing logs
- secret redaction
- that no file contents are stored
- that the hook never exits with an error, even with garbage input or an unwritable log path

## Limitations

- Successful tool calls do not expose an exit code. Non-zero exit codes are visible only through `PostToolUseFailure`.
- Redaction is pattern-based. Review the log before sharing it.
- The `error` text format is described by Claude Code as display text, not a stable format, so the signature rules may need tuning over time.

## License

MIT
