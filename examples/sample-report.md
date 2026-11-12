# Agent Error Tracker Report

Source: `examples\sample-session.jsonl`  
Sessions: 1

## Summary

| Metric | Value |
|---|---|
| Operations observed | 6 |
| Failures (certain) | 3 |
| Failure rate | 50% |
| Suspected failures | 0 |

## Recurring errors

| Error | Occurrences | Tools |
|---|---|---|
| ModuleNotFoundError | 2 | Bash |
| MCP Timeout | 1 | mcp__docs__search |

### ModuleNotFoundError (2)

- Messages: `E   ModuleNotFoundError: No module named 'requests'`
- Operations: `pytest tests/`; `pytest tests/ -x`
- First seen: 2026-11-12T10:00:01Z - last seen: 2026-11-12T10:00:40Z
- Typical cause: A Python module is not importable: missing dependency, wrong virtualenv, or wrong working directory / PYTHONPATH.

### MCP Timeout (1)

- Messages: `MCP error -32001: Request timed out`
- Operations: `mcp__docs__search`
- First seen: 2026-11-12T10:01:30Z - last seen: 2026-11-12T10:01:30Z
- Typical cause: The operation exceeded its time limit: slow or unreachable service, or a command waiting for input.

## Tools involved

| Tool | Operations | Failures |
|---|---|---|
| Bash | 4 | 2 |
| mcp__docs__search | 1 | 1 |
| Read | 1 | 0 |
