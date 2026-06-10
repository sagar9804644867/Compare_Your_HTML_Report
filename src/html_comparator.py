"""
Extract statistics from an HTML report and compare two reports.

Extraction strategy (in order):
  1. Embedded JSON from a report this tool generated (<script id="perf-data">).
  2. Best-effort parse of any aggregate-style statistics <table> (JMeter
     Aggregate Report exports, plugin single-file reports, etc.).
"""

import datetime as _dt
import json
import re

from bs4 import BeautifulSoup

# Map normalised header text -> canonical stat key.
_HEADER_MAP = {
    "label": "label", "transaction": "label", "sampler": "label", "requests": "label",
    "samples": "samples", "samples#": "samples", "count": "samples", "executions": "samples",
    "average": "average", "avg": "average", "averagems": "average",
    "median": "median", "med": "median",
    "90line": "pct90", "90": "pct90", "90thpct": "pct90", "p90": "pct90", "90pct": "pct90",
    "95line": "pct95", "95": "pct95", "95thpct": "pct95", "p95": "pct95", "95pct": "pct95",
    "99line": "pct99", "99": "pct99", "99thpct": "pct99", "p99": "pct99", "99pct": "pct99",
    "min": "min", "minimum": "min",
    "max": "max", "maximum": "max",
    "error": "error_pct", "errorpct": "error_pct", "errors": "error_pct", "error%": "error_pct",
    "throughput": "throughput", "tps": "throughput", "reqs": "throughput", "req/s": "throughput",
    "receivedkbsec": "received_kb_s", "kbsec": "received_kb_s", "received": "received_kb_s",
    "sentkbsec": "sent_kb_s",
}

_NUM_KEYS = ["samples", "average", "median", "pct90", "pct95", "pct99",
             "min", "max", "error_pct", "throughput", "received_kb_s", "sent_kb_s"]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _num(text: str) -> float:
    """Pull a number out of a cell like '1,234.5 ms' or '2.30%'."""
    m = re.search(r"-?[\d,]+\.?\d*", (text or "").replace(",", ""))
    return float(m.group()) if m else 0.0


def _parse_stats_table(soup: BeautifulSoup) -> dict | None:
    best = None
    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all(["td", "th"]) if first_row else []
        mapping = {}
        for idx, th in enumerate(header_cells):
            key = _HEADER_MAP.get(_norm(th.get_text()))
            if key:
                mapping[idx] = key
        # Need a label column plus at least the average to be useful.
        if "label" in mapping.values() and "average" in mapping.values():
            score = len(mapping)
            if best is None or score > best[0]:
                best = (score, table, mapping)
    if not best:
        return None

    _, table, mapping = best
    rows = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < len(mapping):
            continue
        rec = {k: 0.0 for k in _NUM_KEYS}
        rec["label"] = None
        for idx, key in mapping.items():
            if idx >= len(cells):
                continue
            val = cells[idx].get_text(strip=True)
            rec[key] = val if key == "label" else _num(val)
        if rec["label"] and _norm(rec["label"]) not in ("label", ""):
            rows.append(rec)
    if not rows:
        return None

    # Separate an explicit TOTAL row if present.
    overall = None
    txns = []
    for r in rows:
        if _norm(r["label"]) in ("total", "all", "totallabel"):
            overall = r
        else:
            txns.append(r)
    if overall is None and txns:
        overall = _aggregate_overall(txns)

    return {
        "schema": "parsed-table/v1",
        "meta": {"title": "Imported HTML report",
                 "transaction_count": len(txns),
                 "total_samples": int(overall.get("samples", 0)) if overall else 0},
        "overall": overall or {},
        "transactions": txns,
        "series": None,
    }


def _aggregate_overall(txns: list[dict]) -> dict:
    total = sum(t["samples"] for t in txns) or 1
    def wavg(key):  # sample-weighted average
        return round(sum(t[key] * t["samples"] for t in txns) / total, 1)
    return {
        "label": "TOTAL",
        "samples": int(total),
        "average": wavg("average"),
        "median": wavg("median"),
        "pct90": wavg("pct90"),
        "pct95": wavg("pct95"),
        "pct99": wavg("pct99"),
        "min": min((t["min"] for t in txns), default=0),
        "max": max((t["max"] for t in txns), default=0),
        "error_pct": wavg("error_pct"),
        "throughput": round(sum(t["throughput"] for t in txns), 2),
        "received_kb_s": round(sum(t["received_kb_s"] for t in txns), 2),
        "sent_kb_s": 0.0,
    }


def extract_stats_from_html(raw: bytes) -> dict:
    html = raw.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    tag = soup.find(id="perf-data")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            pass

    parsed = _parse_stats_table(soup)
    if parsed:
        return parsed

    raise ValueError(
        "Could not find performance statistics in this HTML file. "
        "Use a report generated by this tool, a JMeter Aggregate Report export, "
        "or a single-file HTML report containing a statistics table."
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

# (metric_key, display name, unit, higher_is_better)
_METRICS = [
    ("samples", "# Samples", "", None),
    ("average", "Average", "ms", False),
    ("median", "Median", "ms", False),
    ("pct90", "90% Line", "ms", False),
    ("pct95", "95% Line", "ms", False),
    ("pct99", "99% Line", "ms", False),
    ("max", "Max", "ms", False),
    ("error_pct", "Error %", "%", False),
    ("throughput", "Throughput", "/s", True),
]

THRESHOLD = 10.0  # % change considered significant


def _delta(a: float, b: float, higher_is_better):
    diff = b - a
    pct = (diff / a * 100) if a else (100.0 if diff else 0.0)
    status = "neutral"
    if higher_is_better is not None and abs(pct) >= THRESHOLD:
        improved = (diff > 0) == higher_is_better
        status = "good" if improved else "bad"
    return round(diff, 2), round(pct, 1), status


def _compare_block(a: dict, b: dict) -> list[dict]:
    out = []
    for key, name, unit, hib in _METRICS:
        av = float(a.get(key, 0) or 0)
        bv = float(b.get(key, 0) or 0)
        diff, pct, status = _delta(av, bv, hib)
        out.append({"metric": name, "unit": unit, "a": av, "b": bv,
                    "diff": diff, "pct": pct, "status": status})
    return out


def compare(stats_a: dict, stats_b: dict, name_a: str, name_b: str) -> dict:
    overall = _compare_block(stats_a.get("overall", {}), stats_b.get("overall", {}))

    txn_a = {t["label"]: t for t in stats_a.get("transactions", [])}
    txn_b = {t["label"]: t for t in stats_b.get("transactions", [])}
    labels = sorted(set(txn_a) | set(txn_b), key=str.lower)

    transactions = []
    for lbl in labels:
        a = txn_a.get(lbl)
        b = txn_b.get(lbl)
        if a and b:
            presence = "both"
            block = _compare_block(a, b)
        elif a:
            presence = "removed"
            block = _compare_block(a, {})
        else:
            presence = "added"
            block = _compare_block({}, b)
        transactions.append({"label": lbl, "presence": presence, "metrics": block})

    return {"name_a": name_a, "name_b": name_b,
            "overall": overall, "transactions": transactions}
