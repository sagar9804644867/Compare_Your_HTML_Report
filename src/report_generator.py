"""
Generate a self-contained HTML performance report from a statistics dict.

The full statistics object is embedded as JSON inside the HTML so that the
comparison module can re-read the exact numbers later (no lossy re-parsing).
Charts use Chart.js from a CDN; the statistics tables work fully offline.
"""

import datetime as _dt
import json

CHART_CDN = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"

_CHART_JS = """
<script>
const S = JSON.parse(document.getElementById('perf-data').textContent).series;
const opts = (t) => ({responsive:true, plugins:{legend:{display:false}},
  scales:{
    x:{ticks:{color:'#8b98a9'}, grid:{color:'#2a3548'}, title:{display:true,text:'time (s)',color:'#8b98a9'}},
    y:{ticks:{color:'#8b98a9'}, grid:{color:'#2a3548'}, title:{display:true,text:t,color:'#8b98a9'}}
  }});
if (window.Chart) {
  new Chart(document.getElementById('rtChart'), {type:'line',
    data:{labels:S.time_s, datasets:[{data:S.avg_response_ms, borderColor:'#4f9cf9',
      backgroundColor:'rgba(79,156,249,.15)', fill:true, tension:.25, pointRadius:0, borderWidth:2}]},
    options:opts('ms')});
  new Chart(document.getElementById('tpChart'), {type:'line',
    data:{labels:S.time_s, datasets:[{data:S.throughput_rps, borderColor:'#3fb950',
      backgroundColor:'rgba(63,185,80,.15)', fill:true, tension:.25, pointRadius:0, borderWidth:2}]},
    options:opts('req/s')});
}
</script>
"""

_CSS = """
:root{--bg:#0f1419;--card:#1a2230;--line:#2a3548;--txt:#e6edf3;--muted:#8b98a9;
--accent:#4f9cf9;--good:#3fb950;--bad:#f85149;--warn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:1200px;margin:0 auto;padding:32px 20px 60px}
header h1{margin:0 0 4px;font-size:24px;font-weight:650}
header .sub{color:var(--muted);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:14px;margin:26px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi .v{font-size:22px;font-weight:680}
.kpi .l{color:var(--muted);font-size:12px;margin-top:4px;text-transform:uppercase;letter-spacing:.04em}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:10px 0 30px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
.panel h3{margin:0 0 12px;font-size:14px;font-weight:600;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:9px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.04em;position:sticky;top:0;background:var(--card)}
tr.total{font-weight:700;background:#202a3a}
.err-ok{color:var(--good)} .err-warn{color:var(--warn)} .err-bad{color:var(--bad)}
.tablewrap{overflow:auto;max-height:560px;border:1px solid var(--line);border-radius:12px}
footer{color:var(--muted);font-size:12px;margin-top:30px;text-align:center}
@media(max-width:760px){.charts{grid-template-columns:1fr}}
"""


def _err_class(pct: float) -> str:
    if pct <= 0:
        return "err-ok"
    if pct < 5:
        return "err-warn"
    return "err-bad"


def _kpi(value, label) -> str:
    return f'<div class="kpi"><div class="v">{value}</div><div class="l">{label}</div></div>'


def _stats_row(r: dict, total: bool = False) -> str:
    cls = ' class="total"' if total else ""
    ec = _err_class(r["error_pct"])
    return (
        f"<tr{cls}><td>{r['label']}</td>"
        f"<td>{r['samples']:,}</td>"
        f"<td>{r['average']:,.0f}</td>"
        f"<td>{r['median']:,.0f}</td>"
        f"<td>{r['pct90']:,.0f}</td>"
        f"<td>{r['pct95']:,.0f}</td>"
        f"<td>{r['pct99']:,.0f}</td>"
        f"<td>{r['min']:,.0f}</td>"
        f"<td>{r['max']:,.0f}</td>"
        f"<td class='{ec}'>{r['error_pct']:.2f}%</td>"
        f"<td>{r['throughput']:,.2f}</td>"
        f"<td>{r['received_kb_s']:,.2f}</td></tr>"
    )


def generate_html_report(stats: dict) -> str:
    meta = stats["meta"]
    ov = stats["overall"]
    ser = stats["series"]
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    head_total = _stats_row({**ov, "label": "TOTAL"}, total=True)
    body_rows = "\n".join(_stats_row(r) for r in stats["transactions"])

    kpis = "".join([
        _kpi(f"{meta['total_samples']:,}", "Samples"),
        _kpi(f"{ov['average']:,.0f} ms", "Avg Response"),
        _kpi(f"{ov['pct90']:,.0f} ms", "90th pct"),
        _kpi(f"{ov['pct99']:,.0f} ms", "99th pct"),
        _kpi(f"{ov['error_pct']:.2f}%", "Error Rate"),
        _kpi(f"{ov['throughput']:,.2f}/s", "Throughput"),
        _kpi(f"{meta['duration_s']:,.0f} s", "Duration"),
    ])

    embedded = json.dumps(stats, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{meta['title']}</title>
<style>{_CSS}</style>
<script src="{CHART_CDN}"></script>
<script type="application/json" id="perf-data">{embedded}</script>
</head><body><div class="wrap">
<header>
  <h1>{meta['title']}</h1>
  <div class="sub">Generated {generated} &middot; {meta['transaction_count']} transactions &middot; self-contained report</div>
</header>

<div class="kpis">{kpis}</div>

<div class="charts">
  <div class="panel"><h3>Average Response Time (ms) over time</h3><canvas id="rtChart" height="160"></canvas></div>
  <div class="panel"><h3>Throughput (req/s) over time</h3><canvas id="tpChart" height="160"></canvas></div>
</div>

<div class="panel" style="padding:0">
  <div class="tablewrap"><table>
    <thead><tr>
      <th>Transaction</th><th>#Samples</th><th>Avg</th><th>Median</th>
      <th>90%</th><th>95%</th><th>99%</th><th>Min</th><th>Max</th>
      <th>Error%</th><th>Throughput</th><th>KB/s</th>
    </tr></thead>
    <tbody>{head_total}{body_rows}</tbody>
  </table></div>
</div>

<footer>Generated by JMeter Performance Utility &middot; interval {ser['interval_s']}s</footer>
</div>
{_CHART_JS}
</body></html>"""
