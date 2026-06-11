"""
Self-contained, JAAR-style sectioned HTML performance report.

Sections (sidebar nav): Overview, Workload Classification, Transaction Metrics,
Slowest Endpoints, Error Analysis, Network & Server Timing, Performance Charts.
Everything is derived from the JTL: scenario header, PASS/FAIL verdict, Apdex,
percentiles incl. p99.9, CoV, TTFB/Connect breakdown, per-minute p90 heatmap,
and time-series charts on a real HH:mm:ss clock axis.
"""

import datetime as _dt
import json

CHART_CDN = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"

_CSS = """
:root{--bg:#0e1525;--card:#161e33;--line:#26304a;--txt:#e6edf3;--muted:#8b98a9;
--accent:#4f9cf9;--good:#3fb950;--bad:#f85149;--warn:#d29922;--purple:#bc8cff;--head:#1b2742;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-size:14px;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
a{color:inherit;text-decoration:none}
.layout{display:flex;align-items:flex-start;max-width:1400px;margin:0 auto}
/* header band */
.band{background:linear-gradient(135deg,#1b2742,#13203a);padding:26px 30px;width:100%}
.band h1{margin:0;font-size:24px;font-weight:700}
.band .gen{color:#9fb0c8;font-size:12.5px;margin-top:4px}
.verdict-badge{display:inline-block;padding:7px 16px;border-radius:8px;font-weight:700;
font-size:14px;margin:14px 0 12px;letter-spacing:.04em}
.verdict-badge.pass{background:rgba(63,185,80,.18);color:#5ee07b;border:1px solid var(--good)}
.verdict-badge.fail{background:rgba(248,81,73,.18);color:#ff7b72;border:1px solid var(--bad)}
.meta-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,auto));
gap:6px 36px;margin-top:8px;font-size:13px}
.meta-grid .k{color:#8b98a9;display:inline-block;min-width:120px}
.meta-grid .v{font-weight:600}
/* sidebar */
.sidebar{position:sticky;top:0;align-self:flex-start;width:230px;flex:0 0 230px;
padding:26px 0;height:100vh;border-right:1px solid var(--line);background:var(--card)}
.sidebar a{display:block;padding:10px 26px;color:var(--muted);font-size:13.5px;
border-left:3px solid transparent}
.sidebar a:hover{color:var(--txt);background:rgba(79,156,249,.07)}
.sidebar a.active{color:var(--accent);border-left-color:var(--accent);background:rgba(79,156,249,.08)}
.content{flex:1;min-width:0;padding:26px 30px 90px}
/* kpis */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:24px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px}
.kpi .v{font-size:21px;font-weight:700}
.kpi .l{color:var(--muted);font-size:10.5px;margin-top:5px;text-transform:uppercase;letter-spacing:.05em}
.kpi .s{color:var(--muted);font-size:10px;margin-top:2px}
/* sections */
section{scroll-margin-top:16px;margin-bottom:30px}
section>h2{font-size:16px;font-weight:650;margin:0 0 14px;padding-left:11px;border-left:3px solid var(--accent)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
.panel h3{margin:0 0 12px;font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.note{color:var(--muted);font-size:12px;margin:-4px 0 12px}
/* class card */
.classbox{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start}
.classkind{font-size:20px;font-weight:700;color:var(--purple);margin-bottom:6px}
.sig{display:grid;grid-template-columns:auto auto;gap:4px 18px;font-size:13px}
.sig .k{color:var(--muted)}
/* tables */
.tablewrap{overflow:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left;max-width:230px;overflow:hidden;text-overflow:ellipsis}
th{color:var(--muted);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;
position:sticky;top:0;background:var(--card);z-index:1}
tr.total td{font-weight:700;background:#1d2840}
tr:hover td{background:#1b2740}
.charts4{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.g{color:var(--good)}.b{color:var(--bad)}.w{color:var(--warn)}.m{color:var(--muted)}.pu{color:var(--purple)}
.badge{font-size:10px;padding:2px 8px;border-radius:20px;border:1px solid;font-weight:600}
.badge.pass{color:var(--good);border-color:var(--good)}.badge.fail{color:var(--bad);border-color:var(--bad)}
.hm-ok{background:rgba(63,185,80,.16);color:#7fd17f}.hm-w{background:rgba(210,153,34,.16);color:var(--warn)}
.hm-b{background:rgba(248,81,73,.16);color:var(--bad)}
.bar{display:inline-block;height:8px;background:var(--accent);border-radius:4px;vertical-align:middle}
footer{color:var(--muted);font-size:11.5px;margin-top:30px;line-height:1.8;border-top:1px solid var(--line);padding-top:16px}
@media(max-width:900px){.sidebar{display:none}.charts4{grid-template-columns:1fr}}
"""

_NAV = [
    ("overview", "Overview"),
    ("classification", "Workload Classification"),
    ("metrics", "Transaction Metrics"),
    ("slowest", "Slowest Endpoints"),
    ("errors", "Error Analysis"),
    ("network", "Network &amp; Server Timing"),
    ("charts", "Performance Charts"),
]


def _ec(p): return "g" if p == 0 else ("w" if p < 5 else "b")
def _ac(s): return "g" if s >= 0.94 else ("w" if s >= 0.85 else "b")
def _hm(v, ref): 
    if ref <= 0: return ""
    r = v / ref
    return "hm-ok" if r < 1.5 else ("hm-w" if r < 3 else "hm-b")
def _kpi(v, l, s=""):
    sub = f'<div class="s">{s}</div>' if s else ""
    return f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div>{sub}</div>'


def _overview(stats):
    meta, ov = stats["meta"], stats["overall"]
    kpis = "".join([
        _kpi(f"{meta['total_samples']:,}", "Total Samples"),
        _kpi(f"{ov['average']:,.0f} ms", "Avg Response"),
        _kpi(f"{ov['pct90']:,.0f} ms", "90th pct"),
        _kpi(f"{ov['pct99']:,.0f} ms", "99th pct"),
        _kpi(f"{ov.get('pct999',0):,.0f} ms", "99.9th pct"),
        _kpi(f'<span class="{_ec(ov["error_pct"])}">{ov["error_pct"]:.2f}%</span>', "Error Rate"),
        _kpi(f"{ov['throughput']:,.2f}/s", "Throughput"),
        _kpi(f'<span class="{_ac(ov.get("apdex",0))}">{ov.get("apdex",0):.3f}</span>',
             f"Apdex T={meta.get('apdex_threshold_ms',500):.0f}ms", ov.get("apdex_rating","")),
        _kpi(f"{meta.get('max_threads',0)}", "Peak VUs"),
        _kpi(f"{meta.get('duration_str','n/a')}", "Duration"),
    ])
    return f'<section id="overview"><h2>Overview</h2><div class="kpis">{kpis}</div></section>'


def _classification(stats):
    c = stats["meta"].get("classification")
    if not c:
        return ""
    sig = "".join(f'<div class="k">{k}</div><div>{v}</div>' for k, v in c["signals"])
    return (
        f'<section id="classification"><h2>Workload Classification</h2>'
        f'<div class="panel"><div class="classbox">'
        f'<div style="flex:1;min-width:240px"><div class="classkind">{c["kind"]}</div>'
        f'<p class="note" style="margin:0">{c["reasoning"]}</p></div>'
        f'<div class="sig">{sig}</div></div></div></section>'
    )


def _metrics(stats):
    has_sla = "sla" in stats["meta"]
    sla_h = "<th>SLA</th>" if has_sla else ""
    head = ("<tr><th>Transaction</th><th>#Samples</th><th>Avg</th><th>Median</th>"
            "<th>p90</th><th>p95</th><th>p99</th><th>p99.9</th><th>Min</th><th>Max</th>"
            "<th>StdDev</th><th>CoV</th><th>Error%</th><th>TPS</th><th>Apdex</th>"
            f"{sla_h}</tr>")
    rows = []
    data = [{"label": "TOTAL", "_t": True, **stats["overall"]}] + stats["transactions"]
    for r in data:
        is_t = r.get("_t", False)
        p90 = r["pct90"]
        sla_td = ""
        if has_sla:
            ok = r.get("sla_pass", True)
            sla_td = f'<td><span class="badge {"pass" if ok else "fail"}">{"PASS" if ok else "FAIL"}</span></td>'
        rows.append(
            f'<tr{" class=total" if is_t else ""}><td>{r["label"]}</td>'
            f'<td>{int(r["samples"]):,}</td><td>{r["average"]:,.0f}</td>'
            f'<td class="{_hm(r["median"],p90)}">{r["median"]:,.0f}</td>'
            f'<td class="{_hm(r["pct90"],p90)}">{r["pct90"]:,.0f}</td>'
            f'<td class="{_hm(r["pct95"],p90)}">{r["pct95"]:,.0f}</td>'
            f'<td class="{_hm(r["pct99"],p90)}">{r["pct99"]:,.0f}</td>'
            f'<td class="{_hm(r.get("pct999",0),p90)}">{r.get("pct999",0):,.0f}</td>'
            f'<td>{r["min"]:,.0f}</td><td>{r["max"]:,.0f}</td>'
            f'<td>{r.get("std",0):,.0f}</td><td class="m">{r.get("cov",0):.0f}%</td>'
            f'<td class="{_ec(r["error_pct"])}">{r["error_pct"]:.2f}%</td>'
            f'<td>{r["throughput"]:,.2f}</td>'
            f'<td class="{_ac(r.get("apdex",0))}">{r.get("apdex",0):.3f}</td>{sla_td}</tr>'
        )
    return (
        f'<section id="metrics"><h2>Transaction Metrics</h2>'
        f'<div class="panel"><div class="tablewrap" style="max-height:440px">'
        f'<table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
        f'<p class="note" style="margin-top:10px">Percentile cells shaded vs the row p90: '
        f'<span class="hm-ok" style="padding:1px 6px;border-radius:4px">&lt;1.5×</span> '
        f'<span class="hm-w" style="padding:1px 6px;border-radius:4px">1.5–3×</span> '
        f'<span class="hm-b" style="padding:1px 6px;border-radius:4px">&gt;3×</span> '
        f'&middot; CoV = response-time variability (lower = steadier).</p>'
        f'</div>{_heatmap_panel(stats)}</section>'
    )


def _heatmap_panel(stats):
    hm = stats.get("heatmap")
    if not hm or not hm.get("buckets") or not hm.get("minutes"):
        return ""
    minutes = hm["minutes"]
    ths = "".join(f"<th>{m}m</th>" for m in minutes)
    rows = []
    for b in hm["buckets"]:
        by_m = {v["minute"]: v for v in b["values"]}
        cells = ""
        for m in minutes:
            v = by_m.get(m)
            if v:
                cells += (f'<td class="{_hm(v["p90"], v["p90"]) or "hm-ok"}" '
                          f'title="p50={v["p50"]} p90={v["p90"]} p99={v["p99"]}">{v["p90"]}</td>')
            else:
                cells += '<td class="m">—</td>'
        rows.append(f"<tr><td>{b['label']}</td>{cells}</tr>")
    return (
        f'<div class="panel"><h3>p90 Response-Time Heatmap (per minute)</h3>'
        f'<p class="note">Each cell is the p90 for that minute; hover for p50/p90/p99. '
        f'Spot exactly when a transaction degraded.</p>'
        f'<div class="tablewrap" style="max-height:320px">'
        f'<table><thead><tr><th>Transaction</th>{ths}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></div>'
    )


def _slowest(stats):
    sl = stats.get("slowest", [])
    if not sl:
        return ""
    rows = "".join(
        f'<tr><td>{i+1}</td><td class="b">{r["elapsed"]:,} ms</td><td>{r["label"]}</td>'
        f'<td>{r["timestamp_s"]:,.0f}s</td><td>{r.get("response_code","")}</td></tr>'
        for i, r in enumerate(sl))
    return (
        f'<section id="slowest"><h2>Slowest Endpoints</h2><div class="panel">'
        f'<h3>Top 10 slowest individual requests</h3>'
        f'<div class="tablewrap"><table><thead><tr><th>#</th><th>Elapsed</th>'
        f'<th>Transaction</th><th>Offset</th><th>HTTP</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div></div></section>'
    )


def _errors(stats):
    codes = stats["overall"].get("error_codes", [])
    detail = stats.get("error_detail", [])
    if not codes and not detail:
        body = '<p class="g" style="margin:0">&#10003; No errors recorded in this run.</p>'
    else:
        crows = "".join(f'<tr><td class="b">{c["code"]}</td><td>{c["count"]:,}</td></tr>' for c in codes)
        drows = "".join(
            f'<tr><td>{r["label"]}</td><td class="b">{r["response_code"]}</td>'
            f'<td>{r.get("message","")}</td><td>{r["elapsed"]:,}</td><td>{r["timestamp_s"]:,.0f}s</td></tr>'
            for r in detail[:20])
        body = (
            f'<p class="note">Error response-code breakdown:</p>'
            f'<table style="max-width:300px;margin-bottom:18px"><thead><tr><th>HTTP Code</th><th>Count</th></tr></thead>'
            f'<tbody>{crows}</tbody></table>'
            f'<p class="note">Individual failed requests (up to 20):</p>'
            f'<div class="tablewrap"><table><thead><tr><th>Transaction</th><th>Code</th>'
            f'<th>Message</th><th>Elapsed</th><th>Offset</th></tr></thead>'
            f'<tbody>{drows}</tbody></table></div>'
        )
    return f'<section id="errors"><h2>Error Analysis</h2><div class="panel">{body}</div></section>'


def _network(stats):
    rows = []
    for r in stats["transactions"]:
        ttfb = r.get("latency_avg", 0)
        connect = r.get("connect_avg", 0)
        total = r["average"]
        processing = max(total - ttfb, 0)
        share = (ttfb / total * 100) if total else 0
        w = int(min(share, 100) * 1.4)
        bar = (f'<span class="bar" style="width:{w}px"></span>'
               f'<span class="m" style="margin-left:6px;font-size:11px">{share:.0f}%</span>')
        rows.append(
            f'<tr><td>{r["label"]}</td><td>{total:,.0f}</td><td>{connect:,.0f}</td>'
            f'<td>{ttfb:,.0f}</td><td>{processing:,.0f}</td><td>{bar}</td></tr>')
    return (
        f'<section id="network"><h2>Network &amp; Server Timing</h2><div class="panel">'
        f'<p class="note">Connect = TCP/TLS setup. TTFB = time to first byte (network + server compute). '
        f'Processing = transfer time after first byte. A high TTFB share points at server-side latency.</p>'
        f'<div class="tablewrap"><table><thead><tr><th>Transaction</th><th>Total (ms)</th>'
        f'<th>Connect</th><th>TTFB</th><th>Processing</th><th>TTFB share</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></div></section>'
    )


def _charts(stats):
    if not stats.get("series"):
        return ('<section id="charts"><h2>Performance Charts</h2>'
                '<div class="panel"><p class="note" style="margin:0">'
                'Time-series charts need event-level data — upload the raw .jtl to see these.</p></div></section>')
    return (
        f'<section id="charts"><h2>Performance Charts</h2>'
        f'<p class="note">Each point is a {stats["series"]["interval_s"]}-second interval.</p>'
        f'<div class="charts4">'
        f'<div class="panel"><h3>Average Response Time over Time (avg + p90)</h3><canvas id="rtChart" height="170"></canvas></div>'
        f'<div class="panel"><h3>Throughput over Time (req/s)</h3><canvas id="tpChart" height="170"></canvas></div>'
        f'<div class="panel"><h3>Active Threads (concurrency)</h3><canvas id="thChart" height="170"></canvas></div>'
        f'<div class="panel"><h3>Errors per Interval</h3><canvas id="erChart" height="170"></canvas></div>'
        f'</div></section>'
    )


_CHART_JS = """
<script>
(function(){
  const D=JSON.parse(document.getElementById('perf-data').textContent), S=D.series;
  // sidebar scroll-spy
  const links=[...document.querySelectorAll('.sidebar a')];
  const secs=links.map(a=>document.querySelector(a.getAttribute('href'))).filter(Boolean);
  const spy=()=>{let i=secs.length-1;for(let k=0;k<secs.length;k++){if(secs[k].getBoundingClientRect().top>120){i=k-1;break;}}
    links.forEach(l=>l.classList.remove('active'));if(i>=0)links[i].classList.add('active');};
  document.addEventListener('scroll',spy,{passive:true});spy();
  if(!window.Chart||!S)return;
  const labels=(S.clock_ms||S.time_s).map(v=>S.clock_ms?new Date(v).toLocaleTimeString('en-GB'):v+'s');
  const ax=(t)=>({ticks:{color:'#8b98a9',maxTicksLimit:8},grid:{color:'#1d2840'},title:{display:true,text:t,color:'#8b98a9',font:{size:11}}});
  const base=(y)=>({responsive:true,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},scales:{x:ax('time'),y:ax(y)}});
  new Chart(rtChart,{type:'line',data:{labels,datasets:[
    {label:'avg',data:S.avg_response_ms,borderColor:'#4f9cf9',backgroundColor:'rgba(79,156,249,.1)',fill:true,tension:.3,pointRadius:1,borderWidth:2},
    {label:'p90',data:S.p90_ms,borderColor:'#d29922',fill:false,tension:.3,pointRadius:0,borderWidth:1.5,borderDash:[4,3]}]},
    options:{...base('ms'),plugins:{legend:{display:true,labels:{color:'#8b98a9',boxWidth:12}},tooltip:{mode:'index',intersect:false}}}});
  new Chart(tpChart,{type:'line',data:{labels,datasets:[{data:S.throughput_rps,borderColor:'#3fb950',backgroundColor:'rgba(63,185,80,.1)',fill:true,tension:.3,pointRadius:1,borderWidth:2}]},options:base('req/s')});
  const thEl=document.getElementById('thChart');
  if(S.threads&&S.threads.some(x=>x>0)){new Chart(thEl,{type:'line',data:{labels,datasets:[{data:S.threads,borderColor:'#bc8cff',backgroundColor:'rgba(188,140,255,.1)',fill:true,stepped:true,pointRadius:0,borderWidth:2}]},options:base('threads')});}
  else if(thEl){thEl.parentElement.innerHTML='<h3>Active Threads (concurrency)</h3><p class="note" style="text-align:center;padding:50px 0">Constant single/low VU run — no ramp.</p>';}
  new Chart(erChart,{type:'bar',data:{labels,datasets:[{data:S.errors,backgroundColor:'rgba(248,81,73,.7)',borderColor:'#f85149',borderWidth:1}]},options:base('errors')});
})();
</script>
"""


def generate_html_report(stats: dict) -> str:
    meta = stats["meta"]
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    verdict = meta.get("verdict", "PASS")
    vclass = "fail" if verdict == "FAIL" else "pass"
    reasons = meta.get("verdict_reasons", [])
    reason_str = (" &mdash; " + "; ".join(reasons)) if reasons else ""

    nav = "".join(f'<a href="#{i}">{label}</a>' for i, label in _NAV)

    meta_rows = "".join(f'<div><span class="k">{k}</span><span class="v">{v}</span></div>' for k, v in [
        ("Scenario", meta.get("scenario_name", "Test Plan")),
        ("Virtual Users", meta.get("max_threads", 0)),
        ("Run Start", meta.get("start_str", "n/a")),
        ("Run End", meta.get("end_str", "n/a")),
        ("Duration", meta.get("duration_str", "n/a")),
        ("Transactions", meta.get("transaction_count", 0)),
        ("Total Samples", f"{meta.get('total_samples',0):,}"),
        ("Source", meta.get("source", "raw JTL")),
    ])

    body = (_overview(stats) + _classification(stats) + _metrics(stats) +
            _slowest(stats) + _errors(stats) + _network(stats) + _charts(stats))

    embedded = json.dumps(stats, separators=(",", ":"))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{meta['title']}</title><style>{_CSS}</style>
<script src="{CHART_CDN}"></script>
<script type="application/json" id="perf-data">{embedded}</script></head>
<body>
<div class="band"><div style="max-width:1400px;margin:0 auto">
  <h1>{meta['title']}</h1>
  <div class="gen">Generated {generated} &middot; JMeter Performance Utility</div>
  <div class="verdict-badge {vclass}">{"&#10007;" if verdict=="FAIL" else "&#10003;"} {verdict}{reason_str}</div>
  <div class="meta-grid">{meta_rows}</div>
</div></div>
<div class="layout">
  <nav class="sidebar">{nav}</nav>
  <div class="content">{body}
    <footer>Apdex T={meta.get('apdex_threshold_ms',500):.0f}ms &middot; CoV = coefficient of variation
    &middot; TTFB = time to first byte &middot; verdict driven by SLA breaches and error rate.
    Self-contained report &mdash; re-uploadable for comparison.</footer>
  </div>
</div>{_CHART_JS}</body></html>"""
