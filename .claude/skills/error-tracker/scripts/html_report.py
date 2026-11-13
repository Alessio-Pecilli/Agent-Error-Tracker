"""Render analyzer stats as a single self-contained HTML page (no external assets, works offline)."""
from __future__ import annotations

from datetime import datetime
from html import escape

from analyzer import HINTS, first_detail

CSS = """
:root{--bg:#f6f7fb;--card:#fff;--ink:#14161f;--muted:#646b7d;--line:#e4e7ef;--accent:#4f46e5;
--fail:#e5484d;--fail-soft:#fdecec;--ok:#2f9e6e;--ok-soft:#e7f6ef;--warn:#c27c0e;--warn-soft:#fdf3e1;--code:#f0f2f7}
@media (prefers-color-scheme:dark){:root{--bg:#0e1016;--card:#171a23;--ink:#eceef4;--muted:#9aa1b2;--line:#272b38;
--accent:#8b85ff;--fail:#ff6b6f;--fail-soft:#3a1c1f;--ok:#4cc38a;--ok-soft:#15302a;--warn:#f0b04a;--warn-soft:#352a14;--code:#1f2330}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:40px 20px 64px}
header{display:flex;align-items:center;gap:14px;margin-bottom:28px}
.logo{width:42px;height:42px;border-radius:12px;background:var(--accent);display:grid;place-items:center;color:#fff;flex:none}
h1{font-size:24px;margin:0;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;word-break:break-all}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:36px 0 14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.kpi .label{color:var(--muted);font-size:13px}
.kpi .value{font-size:34px;font-weight:700;letter-spacing:-.02em;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi.fail .value{color:var(--fail)}.kpi.warn .value{color:var(--warn)}
.meter{height:8px;border-radius:99px;background:var(--ok-soft);overflow:hidden;margin-top:10px}
.meter>span{display:block;height:100%;background:var(--fail);border-radius:99px}
.err{display:grid;grid-template-columns:72px 1fr;gap:18px;margin-bottom:12px}
.count{background:var(--fail-soft);color:var(--fail);border-radius:12px;display:grid;place-items:center;text-align:center;
font-weight:700;font-size:28px;line-height:1.1;padding:10px 0;align-self:start}
.count small{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.err h3{margin:0 0 6px;font-size:18px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.chip{font:12px/1 ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--code);border:1px solid var(--line);
border-radius:99px;padding:5px 9px;color:var(--ink)}
.share{height:6px;border-radius:99px;background:var(--line);overflow:hidden;margin:6px 0 12px}
.share>span{display:block;height:100%;background:var(--fail)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:0;font-size:14px}
dt{color:var(--muted)}dd{margin:0;min-width:0}
code{font:13px ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--code);border-radius:6px;padding:2px 6px;
word-break:break-word}
.hint{margin-top:12px;padding:10px 12px;border-radius:10px;background:var(--ok-soft);font-size:14px}
.hint.none{background:var(--code);color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
th,td{padding:10px 8px;border-bottom:1px solid var(--line)}tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums;width:90px}
.stack{display:flex;height:8px;border-radius:99px;overflow:hidden;background:var(--line);min-width:120px}
.stack .f{background:var(--fail)}.stack .o{background:var(--ok)}
.sus{border-left:4px solid var(--warn);background:var(--warn-soft);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.empty{color:var(--muted);text-align:center;padding:28px}
.note{color:var(--warn);font-size:14px;margin-top:12px}
footer{color:var(--muted);font-size:12px;margin-top:40px;text-align:center}
@media (max-width:560px){.err{grid-template-columns:1fr}.count{grid-auto-flow:column;gap:8px;padding:8px 14px;justify-self:start}}
"""

LOGO = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 9v4M12 17h.01"/>'
        '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>')


def _uniq(values):
    return list(dict.fromkeys(v for v in values if v))


def _error_card(sig: str, evs: list[dict], total_failures: int) -> str:
    n = len(evs)
    tools = "".join(f'<span class="chip">{escape(t)}</span>' for t in sorted({e["tool"] for e in evs}))
    rows = []
    msgs = _uniq(first_detail(e) for e in evs)[:3]
    if msgs:
        rows.append("<dt>Message</dt><dd>" + "<br>".join(f"<code>{escape(m)}</code>" for m in msgs) + "</dd>")
    targets = _uniq(e.get("target") for e in evs)[:3]
    if targets:
        rows.append("<dt>Operation</dt><dd>" + " ".join(f"<code>{escape(t)}</code>" for t in targets) + "</dd>")
    times = sorted(e["ts"] for e in evs if e.get("ts"))
    if times:
        seen = escape(times[0]) if times[0] == times[-1] else f"{escape(times[0])} → {escape(times[-1])}"
        rows.append(f"<dt>Seen</dt><dd>{seen}</dd>")
    hint = HINTS.get(sig.removeprefix("MCP "))
    hint_html = (f'<div class="hint"><strong>Typical cause:</strong> {escape(hint)}</div>' if hint else
                 '<div class="hint none">Not enough information for a cause. Inspect the message above.</div>')
    pct = n / total_failures * 100 if total_failures else 0
    return (f'<article class="card err"><div class="count">{n}<small>{"time" if n == 1 else "times"}</small></div>'
            f'<div><h3>{escape(sig)} {tools}</h3>'
            f'<div class="share" title="{pct:.0f}% of failures"><span style="width:{pct:.1f}%"></span></div>'
            f'<dl>{"".join(rows)}</dl>{hint_html}</div></article>')


def render_html(stats: dict, log_path: str = "", malformed: int = 0) -> str:
    rate = stats["failure_rate"]
    kpis = (
        f'<div class="card kpi"><div class="label">Operations observed</div><div class="value">{stats["total"]}</div></div>'
        f'<div class="card kpi{" fail" if stats["failures"] else ""}"><div class="label">Failures (certain)</div><div class="value">{stats["failures"]}</div></div>'
        f'<div class="card kpi"><div class="label">Failure rate</div><div class="value">{rate:.0f}%</div>'
        f'<div class="meter" role="img" aria-label="{rate:.0f}% failed"><span style="width:{rate:.1f}%"></span></div></div>'
        f'<div class="card kpi{" warn" if stats["suspected"] else ""}"><div class="label">Suspected failures</div><div class="value">{len(stats["suspected"])}</div></div>'
    )
    if stats["groups"]:
        errors = "".join(_error_card(sig, evs, stats["failures"]) for sig, evs in stats["groups"])
    else:
        errors = '<div class="card empty">No failures recorded. 🎉</div>'

    tool_rows = []
    for tool, n, f in stats["tools"]:
        fp = f / n * 100 if n else 0
        tool_rows.append(
            f'<tr><td><span class="chip">{escape(tool)}</span></td><td class="num">{n}</td><td class="num">{f}</td>'
            f'<td><div class="stack" title="{f} failed / {n - f} ok"><span class="f" style="width:{fp:.1f}%"></span>'
            f'<span class="o" style="width:{100 - fp:.1f}%"></span></div></td></tr>')
    tools = ('<div class="card"><table><thead><tr><th>Tool</th><th class="num">Ops</th><th class="num">Failed</th>'
             f'<th>Ratio</th></tr></thead><tbody>{"".join(tool_rows)}</tbody></table></div>') if tool_rows else \
        '<div class="card empty">No operations recorded.</div>'

    suspected = ""
    if stats["suspected"]:
        items = "".join(
            f'<div class="sus"><span class="chip">{escape(e["tool"])}</span> <code>{escape(e.get("target") or "")}</code>'
            f'<div style="margin-top:6px"><code>{escape(first_detail(e))}</code></div></div>'
            for e in stats["suspected"][:10])
        suspected = ('<h2>Suspected failures</h2><p class="sub">The tool reported success, but its output contains '
                     f'error-like text. Not counted in the failure rate — verify manually.</p>{items}')

    note = f'<p class="note">{malformed} malformed log line(s) were skipped.</p>' if malformed else ""
    source = f"Source: {escape(log_path)} · " if log_path else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Error Tracker Report</title><style>{CSS}</style></head>
<body><main>
<header><div class="logo">{LOGO}</div><div><h1>Agent Error Tracker</h1>
<div class="sub">{source}{stats["sessions"]} session(s) · generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</div></div></header>
<section class="kpis">{kpis}</section>{note}
<h2>Recurring errors</h2>{errors}
<h2>Tools involved</h2>{tools}
{suspected}
<footer>Generated locally by Agent Error Tracker · statistics come only from recorded hook events</footer>
</main></body></html>
"""
