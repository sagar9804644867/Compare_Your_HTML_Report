"""Render a side-by-side comparison HTML report from a comparison dict."""

import datetime as _dt

from .report_generator import _CSS

_EXTRA_CSS = """
.legend{display:flex;gap:18px;margin:8px 0 18px;font-size:12px;color:var(--muted);flex-wrap:wrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
.dot.good{background:var(--good)}.dot.bad{background:var(--bad)}.dot.neutral{background:var(--muted)}
.up{color:var(--bad)}.down{color:var(--good)}
.good-txt{color:var(--good)}.bad-txt{color:var(--bad)}.neutral-txt{color:var(--muted)}
.names{display:flex;gap:14px;margin:6px 0 14px;flex-wrap:wrap}
.names .n{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font-size:13px}
.names .n b{color:var(--accent)}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:14px 0 20px}
.scard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.scard .v{font-size:22px;font-weight:700}.scard .l{color:var(--muted);font-size:11px;text-transform:uppercase}
.verdict{border-radius:12px;padding:16px 20px;margin:6px 0 6px;font-size:16px;font-weight:700}
.verdict.pass{background:rgba(63,185,80,.12);border:1px solid var(--good);color:var(--good)}
.verdict.fail{background:rgba(248,81,73,.12);border:1px solid var(--bad);color:var(--bad)}
.tag{font-size:10px;padding:2px 8px;border-radius:20px;border:1px solid var(--line);color:var(--muted)}
.tag.added{color:var(--good);border-color:var(--good)}
.tag.removed{color:var(--bad);border-color:var(--bad)}
.tag.regression{color:var(--bad);border-color:var(--bad)}
.tag.improvement{color:var(--good);border-color:var(--good)}
.tag.stable{color:var(--muted)}
section{margin:24px 0}
section h2{font-size:15px;font-weight:620;border-left:3px solid var(--accent);padding-left:10px}
"""


def _fmt(v, unit):
    if unit == "%":
        return f"{v:,.2f}%"
    if unit == "":
        return f"{v:,.3f}" if v and v < 2 else f"{v:,.0f}"
    return f"{v:,.0f}"


def _pct_cell(pct, status):
    if status == "good":
        return f'<td class="good-txt">{"&#9660;" if pct<0 else "&#9650;"} {pct:+.1f}%</td>'
    if status == "bad":
        return f'<td class="bad-txt">{"&#9650;" if pct>0 else "&#9660;"} {pct:+.1f}%</td>'
    return f'<td class="neutral-txt">{pct:+.1f}%</td>'


def _metric_table(block):
    rows = "".join(
        f"<tr><td>{m['metric']}</td><td>{_fmt(m['a'],m['unit'])}</td>"
        f"<td>{_fmt(m['b'],m['unit'])}</td><td>{m['diff']:+,.2f}</td>"
        f"{_pct_cell(m['pct'],m['status'])}</tr>" for m in block
    )
    return ("<table><thead><tr><th>Metric</th><th>Baseline (A)</th><th>Current (B)</th>"
            f"<th>&Delta;</th><th>&Delta;%</th></tr></thead><tbody>{rows}</tbody></table>")


def _txn_section(transactions):
    blocks = []
    for t in transactions:
        tags = f'<span class="tag {t["verdict"]}">{t["verdict"]}</span>'
        if t["presence"] == "added":
            tags += ' <span class="tag added">new in B</span>'
        elif t["presence"] == "removed":
            tags += ' <span class="tag removed">only in A</span>'
        blocks.append(
            f'<div class="panel" style="margin-bottom:14px">'
            f'<h3 style="color:var(--txt);font-size:14px">{t["label"]} &nbsp;{tags}</h3>'
            f'{_metric_table(t["metrics"])}</div>'
        )
    return "".join(blocks)


def generate_comparison_html(cmp: dict) -> str:
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s = cmp["summary"]
    vclass = "fail" if s["verdict"] == "FAIL" else "pass"
    worst = (f' &middot; worst: {s["worst_label"]} ({s["worst_pct"]:+.1f}%)'
             if s["worst_label"] else "")
    verdict = (f'<div class="verdict {vclass}">Overall verdict: {s["verdict"]} — '
               f'{s["regressions"]} regression(s), {s["improvements"]} improvement(s){worst}</div>')

    summary_cards = "".join([
        f'<div class="scard"><div class="v">{s["total"]}</div><div class="l">Transactions</div></div>',
        f'<div class="scard"><div class="v bad-txt">{s["regressions"]}</div><div class="l">Regressions</div></div>',
        f'<div class="scard"><div class="v good-txt">{s["improvements"]}</div><div class="l">Improvements</div></div>',
        f'<div class="scard"><div class="v neutral-txt">{s["stable"]}</div><div class="l">Stable</div></div>',
    ])

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Performance Comparison Report</title>
<style>{_CSS}{_EXTRA_CSS}</style></head>
<body><div class="wrap">
<header><h1>Performance Comparison Report</h1>
<div class="sub">Generated {generated} &middot; Baseline (A) vs Current (B) &middot; threshold &plusmn;10%</div></header>
<div class="names">
  <div class="n"><b>A &middot; Baseline</b> &nbsp;{cmp['name_a']}</div>
  <div class="n"><b>B &middot; Current</b> &nbsp;{cmp['name_b']}</div>
</div>
{verdict}
<div class="summary">{summary_cards}</div>
<div class="legend">
  <span><span class="dot good"></span>Improvement (&ge;10%)</span>
  <span><span class="dot bad"></span>Regression (&ge;10%)</span>
  <span><span class="dot neutral"></span>Within threshold</span>
</div>
<section><h2>Overall</h2><div class="panel">{_metric_table(cmp['overall'])}</div></section>
<section><h2>By Transaction (regressions first)</h2>{_txn_section(cmp['transactions'])}</section>
<footer>For response time &amp; errors, lower is better; for throughput &amp; Apdex, higher is better.
Verdict is driven by 90%/95%/error regressions beyond 10%.</footer>
</div></body></html>"""
