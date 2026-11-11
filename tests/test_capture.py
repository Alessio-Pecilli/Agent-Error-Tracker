import json
import subprocess
import sys
from pathlib import Path

import capture

SCRIPT = Path(capture.__file__)


def run_hook(payload, log):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    env = {"AGENT_ERROR_TRACKER_LOG": str(log), "PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    return subprocess.run([sys.executable, str(SCRIPT)], input=data.encode(), capture_output=True, env=env, timeout=30)


def test_failure_event_is_recorded_and_redacted(tmp_path):
    log = tmp_path / "events.jsonl"
    payload = {
        "session_id": "s1", "hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
        "tool_input": {"command": "curl -H 'Authorization: Bearer abc.def' https://x --password hunter2"},
        "tool_use_id": "toolu_1", "error": "Exit code 1\ntoken=ghp_abcdefghijklmnopqrstuvwxyz123456 failed",
        "is_interrupt": False, "duration_ms": 42,
    }
    r = run_hook(payload, log)
    assert r.returncode == 0
    rec = json.loads(log.read_text(encoding="utf-8"))
    assert rec["ok"] is False and rec["tool"] == "Bash" and rec["duration_ms"] == 42
    dumped = json.dumps(rec)
    for secret in ("abc.def", "hunter2", "ghp_abcdef"):
        assert secret not in dumped
    assert rec["error"].startswith("Exit code 1")


def test_success_event_keeps_no_file_content(tmp_path):
    log = tmp_path / "events.jsonl"
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_use_id": "t",
               "tool_input": {"file_path": "/p/a.py", "content": "SECRET_CONTENT"},
               "tool_response": {"filePath": "/p/a.py"}}
    assert run_hook(payload, log).returncode == 0
    rec = json.loads(log.read_text(encoding="utf-8"))
    assert rec["ok"] is True and rec["target"] == "/p/a.py"
    assert "SECRET_CONTENT" not in log.read_text(encoding="utf-8")


def test_bash_stderr_kept_as_output_tail():
    rec = capture.build_record({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                "tool_input": {"command": "make"}, "tool_response": {"stdout": "", "stderr": "warning: x"}})
    assert rec["output_tail"] == "warning: x"


def test_webfetch_query_string_dropped():
    assert capture.target_of("WebFetch", {"url": "https://api.example.com/v1/x?key=SECRET"}) == "https://api.example.com/v1/x"


def test_long_error_keeps_first_line_and_tail():
    text = "Exit code 1\n" + "x" * 5000 + "\nModuleNotFoundError: No module named 'y'"
    clipped = capture.clip(text)
    assert len(clipped) <= capture.MAX_TEXT
    assert clipped.startswith("Exit code 1") and clipped.endswith("'y'")


def test_garbage_input_never_fails(tmp_path):
    log = tmp_path / "events.jsonl"
    for bad in ("", "not json", "[1,2]", json.dumps({"hook_event_name": "Stop"})):
        assert run_hook(bad, log).returncode == 0
    assert not log.exists()


def test_unwritable_log_still_exits_zero(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_input": {}}
    assert run_hook(payload, blocker / "sub" / "events.jsonl").returncode == 0
