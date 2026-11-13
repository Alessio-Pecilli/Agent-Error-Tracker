import json
from pathlib import Path

import analyzer

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample-session.jsonl"


def ev(**kw):
    base = {"tool": "Bash", "ok": True}
    base.update(kw)
    return base


def test_sample_session_matches_expected_stats():
    events, bad = analyzer.load_events(SAMPLE)
    stats = analyzer.analyze(events)
    assert bad == 0
    assert stats["total"] == 6
    assert stats["failures"] == 3
    assert round(stats["failure_rate"]) == 50
    assert {sig: len(evs) for sig, evs in stats["groups"]} == {"ModuleNotFoundError": 2, "MCP Timeout": 1}
    assert stats["suspected"] == []


def test_signature_classification():
    assert analyzer.signature(ev(ok=False, error="Exit code 1\nE ModuleNotFoundError: x")) == "ModuleNotFoundError"
    assert analyzer.signature(ev(tool="mcp__a__b", ok=False, error="Request timed out")) == "MCP Timeout"
    assert analyzer.signature(ev(ok=False, error="Command timed out after 2m")) == "Timeout"
    assert analyzer.signature(ev(ok=False, error="Exit code 127\nbash: foo: command not found")) == "Exit code 127"
    assert analyzer.signature(ev(ok=False, is_interrupt=True, error="aborted")) == "Interrupted"
    assert analyzer.signature(ev(tool="Edit", ok=False, error="String to replace not found in file 3")) == \
        "String to replace not found in file N"


def test_duplicate_tool_use_id_counted_once_and_failure_wins():
    events = [ev(tool_use_id="a", ok=True), ev(tool_use_id="a", ok=False, error="Exit code 1"), ev(tool_use_id="b")]
    stats = analyzer.analyze(events)
    assert stats["total"] == 2
    assert stats["failures"] == 1


def test_suspected_only_for_successful_ops_with_error_text():
    events = [
        ev(output_tail="Traceback (most recent call last):\nValueError: bad"),
        ev(output_tail="all good"),
        ev(ok=False, error="Exit code 1", output_tail="Traceback (most recent call last):"),
    ]
    stats = analyzer.analyze(events)
    assert len(stats["suspected"]) == 1
    assert stats["failures"] == 1


def test_load_skips_malformed_lines(tmp_path):
    log = tmp_path / "events.jsonl"
    log.write_text("not json\n\n" + json.dumps(ev()) + "\n[1,2]\n", encoding="utf-8")
    events, bad = analyzer.load_events(log)
    assert len(events) == 1 and bad == 2


def test_empty_log_reports_no_failures(tmp_path):
    stats = analyzer.analyze([])
    assert stats["total"] == 0 and stats["failure_rate"] == 0
    assert "No failures recorded." in analyzer.render(stats)


def test_report_contains_key_sections():
    events, _ = analyzer.load_events(SAMPLE)
    report = analyzer.render(analyzer.analyze(events))
    assert "| Operations observed | 6 |" in report
    assert "| Failure rate | 50% |" in report
    assert "| ModuleNotFoundError | 2 | Bash |" in report
    assert "| MCP Timeout | 1 | mcp__docs__search |" in report
    assert "No module named 'requests'" in report


def test_unknown_error_gets_no_invented_hint():
    report = analyzer.render(analyzer.analyze([ev(tool="Edit", ok=False, error="weird thing")]))
    assert "not enough information" in report


def test_cli_missing_log_returns_1(tmp_path, capsys):
    assert analyzer.main([str(tmp_path / "nope.jsonl")]) == 1
    assert "No event log found" in capsys.readouterr().err


def test_cli_writes_report(tmp_path):
    out = tmp_path / "r.md"
    assert analyzer.main([str(SAMPLE), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Agent Error Tracker Report")


def test_html_report(tmp_path):
    import html_report

    events, _ = analyzer.load_events(SAMPLE)
    events.append({"tool": "Bash", "ok": False, "target": "<script>x</script>", "error": "weird <b>"})
    page = html_report.render_html(analyzer.analyze(events))
    assert page.startswith("<!doctype html>")
    assert ">7</div>" in page and ">4</div>" in page  # operations, failures
    assert "ModuleNotFoundError" in page and "MCP Timeout" in page
    assert "<script>x" not in page and "&lt;script&gt;" in page  # escaped
    assert "Not enough information" in page


def test_cli_html_flag(tmp_path):
    out = tmp_path / "r.md"
    assert analyzer.main([str(SAMPLE), "-o", str(out), "--html"]) == 0
    assert (tmp_path / "r.html").read_text(encoding="utf-8").startswith("<!doctype html>")
