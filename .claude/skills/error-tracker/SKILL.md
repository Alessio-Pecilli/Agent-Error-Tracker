---
name: error-tracker
description: Analyze the tool failures recorded by the Agent Error Tracker hooks during Claude Code sessions and present a diagnostic report of recurring errors, failure rate and tools involved. Use when the user asks about failed tool calls, recurring errors or why commands keep failing.
argument-hint: "[path/to/events.jsonl]"
allowed-tools: Bash(python *) Bash(python3 *) Read
---

# Error Tracker

Produce a diagnostic report from the local tool-event log and summarize it for the user.

## Steps

1. Run the analyzer (pass `$ARGUMENTS` as the log path if the user gave one; otherwise it uses `.claude/error-tracker/events.jsonl` in the project):

   ```
   python "${CLAUDE_SKILL_DIR}/scripts/analyzer.py" $ARGUMENTS
   ```

   If `python` is not found, retry with `python3`.

2. If it exits with "No event log found", tell the user the hooks are not installed or no session has been recorded yet, point them to the "Installation" section of the project README, and stop.

3. Read the Markdown report at the path printed on the first output line ("Report written to ...").

4. Present the results:
   - One line with operations observed, failures, failure rate, suspected failures.
   - The recurring errors, most frequent first, each with occurrences, tools, an example message and the operation that failed.
   - The tools with the most failures.
   - Suspected failures, clearly labelled as unconfirmed.
   - The report path, so the user can open the full file.

## Rules

- Use only the data in the report. If the report says there is not enough information for a cause, say so; do not invent a diagnosis.
- Keep "certain" failures (reported by the tool) separate from "suspected" ones (error text in a successful output).
- Do not modify any project files. You may suggest a next step (for example installing a missing module), but do not run it unless the user asks.
