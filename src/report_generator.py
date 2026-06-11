"""Generate a self-contained HTML performance report from a statistics dict."""

import datetime as _dt
import json

CHART_CDN = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"

_CSS = """
:root{--bg:#0f1419;--card:#1a2230;--line:#2a3548;--txt:#e6edf3;--muted:#8b98a9;
--accent:#4f9cf9;--good:#3fb950;--bad:#f85149;--warn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:1280px;margin:0 auto;padding:32px 20px 60px}
header h1{margin:0 0 4px;font-size:24px;font-weight:650}
header .sub{color:var(--muted);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;margin:24px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi .v{font-size:22px;font-weight:680}
.kpi .l{color:var(--muted);font-size:12px;margin-top:4px;text-transform:uppercase;letter-spacing:.04em}
.banner{border-radius:12px;padding:14px 18px;margin:6px 0 22px;font-weight:600;font-size:14px}
.banner.pass{background:rgba(63,185,80,.12);border:1px solid var(--good);color:var(--good)}
.banner.fail{background:rgba(248,81,73,.12);border:1px solid var(--bad);color:var(--bad)}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:10px 0 26px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
.panel h3{margin:0 0 12px;font-size:14px;font-weight:600;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:9px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.04em;position:sticky;top:0;background:var(--card)}
tr.total{font-weight:700;background:#202a3a}
.err-ok{color:var(--good)}.err-warn{color:var(--warn)}.err-bad{color:var(--bad)}
.badge{font-size:10px;padding:2px 8px;border-radius:20px;border:1px solid}
.badge.pass{color:var(--good);border-color:var(--good)}
.badge.fail{color:var(--bad);border-color:var(--bad)}
.tablewrap{overflow:auto;max-height:560px;border:1px solid var(--line);border-radius:12px}
.apdex-x{color:var(--good)}.apdex-g{color:#7fd17f}.apdex-f{color:var(--warn)}
.apdex-p{color:#f0883e}.apdex-u{color:var(--bad)}
footer{color:var(--muted);font-size:12px;margin-top:30px;text-align:center}
@media(max-width:760px){.charts{grid-template-columns:1fr}}
"""

_CHART_JS = """
<script>
const D = JSON.parse(document.getElementById('perf-data').textContent);
const S = D.series;
if (window.Chart && S) {
  const ax=(t)=>({ticks:{color:'#8b98a9'},grid:{color:'#2a3548'},title:{display:true,text:t,color:'#8b98a9'}});
  const base=(t)=>({responsive:true,plugins:{legend:{display:false}},scales:{x:ax('time (s)'),y:ax(t)}});
  new Chart(document.getElementById('rtChart'),{type:'line',
    data:{labels:S.time_s,datasets:[{data:S.avg_response_ms,borderColor:'#4f9cf9',
      backgroundColor:'rgba(79,156,249,.15)',fill:true,tension:.25,pointRadius:0,borderWidth:2}]},
    options:base('ms')});
  new Chart(document.getElementById('tpChart'),{type:'line',
    data:{labels:S.time_s,datasets:[{data:S.throughput_rps,borderColor:'#3fb950',
      backgroundColor:'rgba(63,185,80,.15)',fill:true,tension:.25,pointRadius:0,borderWidth:2}]},
    options:base('req/s')});
  if (S.threads && S.threads.some(x=>x>0)) {
    new Chart(document.getElementById('thChart'),{type:'line',
      data:{labels:S.time_s,datasets:[{data:S.threads,borderColor:'#d29922',
        backgroundColor:'rgba(210,153,34,.12)',fill:true,stepped:true,pointRadius:0,borderWidth:2}]},
      options:base('active threads')});
  }
  if (S.errors && S.errors.some(x=>x>0)) {
    new Chart(document.getElementById('erChart'),{type:'bar',
      data:{labels:S.time_s,datasets:[{data:S.errors,backgroundColor:'#f85149'}]},
      options:base('errors')});
  }
}
</script>
"""

_APDEX_CLASS = {"Excellent": "apdex-x", "Good": "apdex-g", "Fair": "apdex-f",
                "Poor": "apdex-p", "Unacceptable": "apdex-u", "n/a": "muted"}


def _err_class(pct):
    return "err-ok" if pct <= 0 else ("err-warn" if pct < 5 else "err-bad")


def _kpi(v, l):
    return f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>'


def _apdex_cell(r):
    cls = _APDEX_CLASS.get(r.get("apdex_rating", "n/a"), "muted")
    val = r.get("apdex", 0)
    return f'<td class="{cls}">{val:.3f}</td>'


def _row(r, has_sla, total=False):
    cls = ' class="total"' if total else ""
    sla = ""
    if has_sla:
        ok = r.get("sla_pass", True)
        sla = f'<td><span class="badge {"pass" if ok else "fail"}">{"PASS" if ok else "FAIL"}</span></td>'
    return (
        f"<tr{cls}><td>{r['label']}</td>"
        f"<td>{r['samples']:,.0f}</td>"
        f"<td>{r['average']:,.0f}</td><td>{r['median']:,.0f}</td>"
        f"<td>{r['pct90']:,.0f}</td><td>{r['pct95']:,.0f}</td>"
        f"<td>{r['pct99']:,.0f}</td><td>{r.get('pct999',0):,.0f}</td>"
        f"<td>{r['max']:,.0f}</td>"
        f"<td>{r.get('cov',0):,.0f}%</td>"
        f"<td class='{_err_class(r['error_pct'])}'>{r['error_pct']:.2f}%</td>"
        f"<td>{r['throughput']:,.2f}</td>"
        f"{_apdex_cell(r)}{sla}</tr>"
    )


def _error_panel(stats):
    codes = stats["overall"].get("error_codes") or []
    if not codes:
        rows = "<tr><td>None</td><td>0</td></tr>"
    else:
        rows = "".join(f"<tr><td>{c['code']}</td><td>{c['count']:,}</td></tr>" for c in codes)
    return (f'<div class="panel"><h3>Top error response codes (overall)</h3>'
            f'<table><thead><tr><th>Response code</th><th>Count</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def generate_html_report(stats: dict) -> str:
    meta, ov, ser = stats["meta"], stats["overall"], stats.get("series")
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    has_sla = "sla" in meta

    kpis = "".join([
        _kpi(f"{meta['total_samples']:,}", "Samples"),
        _kpi(f"{ov['average']:,.0f} ms", "Avg Response"),
        _kpi(f"{ov['pct90']:,.0f} ms", "90th pct"),
        _kpi(f"{ov['pct99']:,.0f} ms", "99th pct"),
        _kpi(f"{ov['error_pct']:.2f}%", "Error Rate"),
        _kpi(f"{ov['throughput']:,.2f}/s", "Throughput"),
        _kpi(f"{ov.get('apdex',0):.3f}", f"Apdex (T={meta.get('apdex_threshold_ms',500):.0f}ms)"),
        _kpi(f"{meta.get('duration_s',0):,.0f} s", "Duration"),
    ])

    banner = ""
    if has_sla:
        failed = meta.get("sla_failed", 0)
        if failed:
            banner = f'<div class="banner fail">SLA: FAIL — {failed} transaction(s) breached targets</div>'
        else:
            banner = '<div class="banner pass">SLA: PASS — all transactions within targets</div>'

    sla_th = "<th>SLA</th>" if has_sla else ""
    head = (f"<tr><th>Transaction</th><th>#Samples</th><th>Avg</th><th>Median</th>"
            f"<th>90%</th><th>95%</th><th>99%</th><th>99.9%</th><th>Max</th>"
            f"<th>CoV</th><th>Error%</th><th>TPS</th><th>Apdex</th>{sla_th}</tr>")
    body = _row({**ov, "label": "TOTAL"}, has_sla, total=True) + \
        "".join(_row(r, has_sla) for r in stats["transactions"])

    charts = ""
    if ser:
        charts = (
            '<div class="charts">'
            '<div class="panel"><h3>Avg Response Time (ms)</h3><canvas id="rtChart" height="150"></canvas></div>'
            '<div class="panel"><h3>Throughput (req/s)</h3><canvas id="tpChart" height="150"></canvas></div>'
            '<div class="panel"><h3>Active Threads</h3><canvas id="thChart" height="150"></canvas></div>'
            '<div class="panel"><h3>Errors over time</h3><canvas id="erChart" height="150"></canvas></div>'
            '</div>'
        )

    embedded = json.dumps(stats, separators=(",", ":"))
    source_note = meta.get("source", "self-contained report")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{meta['title']}</title><style>{_CSS}</style>
<script src="{CHART_CDN}"></script>
<script type="application/json" id="perf-data">{embedded}</script></head>
<body><div class="wrap">
<header><h1>{meta['title']}</h1>
<div class="sub">Generated {generated} &middot; {meta['transaction_count']} transactions &middot; {source_note}</div></header>
{banner}
<div class="kpis">{kpis}</div>
{charts}
<div class="panel" style="padding:0;margin-bottom:18px">
  <div class="tablewrap"><table><thead>{head}</thead><tbody>{body}</tbody></table></div>
</div>
{_error_panel(stats)}
<footer>Generated by JMeter Performance Utility &middot; Apdex T={meta.get('apdex_threshold_ms',500):.0f}ms
&middot; CoV = response-time variability (lower = more consistent)</footer>
</div>{_CHART_JS}</body></html>"""
