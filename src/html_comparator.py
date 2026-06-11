"""
Extract statistics from a report (HTML / CSV / JTL) and compare two of them.

HTML extraction tries, in order:
  1. Embedded JSON written by this tool (<script id="perf-data">).
  2. JSON/JS data embedded in ANY <script> block (covers JMeter dashboard
     statistics.json-style data and many plugin reports that render their table
     client-side -- the usual reason a parser sees an "empty" table).
  3. A static aggregate-style <table>.
"""

import json
import re

from bs4 import BeautifulSoup

from .jtl_parser import (
    build_stats_from_summary, compute_statistics, load_csv_any, load_jtl, _norm,
)

# Canonical alias map for BOTH HTML headers and JSON keys (normalised).
KEY_MAP = {
    "label": "label", "transaction": "label", "sampler": "label", "requests": "label",
    "samples": "samples", "samplecount": "samples", "count": "samples", "executions": "samples",
    "executionssamples": "samples", "numberofsamples": "samples",
    "average": "average", "avg": "average", "meanrestime": "average",
    "median": "median", "med": "median", "medianrestime": "median",
    "90line": "pct90", "90thpct": "pct90", "p90": "pct90", "90pct": "pct90",
    "pct1restime": "pct90", "90": "pct90",
    "95line": "pct95", "95thpct": "pct95", "p95": "pct95", "95pct": "pct95",
    "pct2restime": "pct95", "95": "pct95",
    "99line": "pct99", "99thpct": "pct99", "p99": "pct99", "99pct": "pct99",
    "pct3restime": "pct99", "99": "pct99",
    "min": "min", "minimum": "min", "minrestime": "min",
    "max": "max", "maximum": "max", "maxrestime": "max",
    "error": "error_pct", "errorpct": "error_pct", "errors": "error_pct",
    "throughput": "throughput", "tps": "throughput", "transactionss": "throughput",
    "transactionspersec": "throughput", "reqs": "throughput",
    "receivedkbsec": "received_kb_s", "kbsec": "received_kb_s", "received": "received_kb_s",
    "receivedkbytespersec": "received_kb_s",
    "sentkbsec": "sent_kb_s", "sent": "sent_kb_s", "sentkbytespersec": "sent_kb_s",
}

_NUM = re.compile(r"-?[\d,]+\.?\d*")


def _num(text) -> float:
    m = _NUM.search(str(text).replace(",", ""))
    return float(m.group()) if m else 0.0


# --------------------------------------------------------------------------- #
# JSON-in-script extraction
# --------------------------------------------------------------------------- #
def _balanced_blobs(text: str):
    """Yield substrings that are balanced {...} or [...] blocks."""
    opens = {"{": "}", "[": "]"}
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in opens:
            depth, j, in_str, esc, q = 0, i, False, False, ""
            while j < n:
                c = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == q:
                        in_str = False
                elif c in ("'", '"'):
                    in_str, q = True, c
                elif c in opens:
                    depth += 1
                elif c in ("}", "]"):
                    depth -= 1
                    if depth == 0:
                        yield text[i:j + 1]
                        i = j
                        break
                j += 1
        i += 1


def _rows_from_obj(obj) -> list[dict] | None:
    """Turn a parsed JSON object/array into summary rows if it looks like stats."""
    candidates = []
    if isinstance(obj, list):
        candidates = [x for x in obj if isinstance(x, dict)]
    elif isinstance(obj, dict):
        # dict mapping label -> metrics
        for k, v in obj.items():
            if isinstance(v, dict):
                row = dict(v)
                row.setdefault("label", k)
                candidates.append(row)
        # or a wrapper containing a list under some key
        if not candidates:
            for v in obj.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    candidates = v
                    break
    if not candidates:
        return None

    rows, mapped_metric = [], False
    for c in candidates:
        rec = {}
        for k, val in c.items():
            key = KEY_MAP.get(_norm(str(k)))
            if not key:
                continue
            rec[key] = str(val) if key == "label" else _num(val)
            if key not in ("label",):
                mapped_metric = True
        if rec.get("label") and any(m in rec for m in ("average", "pct90", "pct99")):
            rows.append(rec)
    return rows if (rows and mapped_metric) else None


def _extract_from_scripts(soup: BeautifulSoup) -> list[dict] | None:
    best = None
    for script in soup.find_all("script"):
        body = script.string or script.get_text() or ""
        if not body or not any(h in body.lower() for h in
                               ("average", "restime", "throughput", "samplecount", "90")):
            continue
        for blob in _balanced_blobs(body):
            if len(blob) < 20:
                continue
            try:
                obj = json.loads(blob)
            except (json.JSONDecodeError, ValueError):
                continue
            rows = _rows_from_obj(obj)
            if rows and (best is None or len(rows) > len(best)):
                best = rows
    return best


# --------------------------------------------------------------------------- #
# Static HTML table extraction
# --------------------------------------------------------------------------- #
def _parse_stats_table(soup: BeautifulSoup) -> list[dict] | None:
    best = None
    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        if not header_cells:
            first = table.find("tr")
            header_cells = first.find_all(["td", "th"]) if first else []
        mapping = {}
        for idx, th in enumerate(header_cells):
            key = KEY_MAP.get(_norm(th.get_text()))
            if key:
                mapping[idx] = key
        if "label" in mapping.values() and "average" in mapping.values():
            score = len(mapping)
            if best is None or score > best[0]:
                best = (score, table, mapping)
    if not best:
        return None
    _, table, mapping = best
    body = table.find("tbody") or table
    rows = []
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < len(mapping):
            continue
        rec = {}
        for idx, key in mapping.items():
            if idx < len(cells):
                val = cells[idx].get_text(strip=True)
                rec[key] = val if key == "label" else _num(val)
        if rec.get("label") and _norm(rec["label"]) not in ("label", ""):
            rows.append(rec)
    return rows or None


# --------------------------------------------------------------------------- #
# Public extraction
# --------------------------------------------------------------------------- #
def extract_stats_from_html(raw: bytes, title: str = "Imported report") -> dict:
    html = raw.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    tag = soup.find(id="perf-data")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            pass

    rows = _extract_from_scripts(soup)
    if not rows:
        rows = _parse_stats_table(soup)
    if rows:
        return build_stats_from_summary(rows, title)

    raise ValueError(
        "Could not find performance statistics in this HTML file. The data may be "
        "rendered in a format this parser doesn't recognise yet. Easiest fixes: "
        "(a) export a JMeter Aggregate/Summary report as CSV and upload that, or "
        "(b) upload the raw .jtl and let this tool build the report."
    )


def extract_stats_from_upload(name: str, raw: bytes, title: str | None = None) -> dict:
    """Route any supported upload (.html/.csv/.jtl/.xml) to a stats dict."""
    title = title or name
    lower = name.lower()
    if lower.endswith((".html", ".htm")):
        return extract_stats_from_html(raw, title)
    if lower.endswith(".csv"):
        return load_csv_any(raw, title)
    if lower.endswith((".jtl", ".xml")):
        return compute_statistics(load_jtl(raw), title)
    # Unknown extension: sniff.
    head = raw.lstrip()[:64].lower()
    if head.startswith(b"<"):
        return extract_stats_from_html(raw, title)
    return load_csv_any(raw, title)


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
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
    ("apdex", "Apdex", "", True),
]
_KEY_METRICS = {"pct90", "pct95", "error_pct"}  # drive the regression verdict
THRESHOLD = 10.0


def _delta(a, b, higher_is_better):
    diff = b - a
    pct = (diff / a * 100) if a else (100.0 if diff else 0.0)
    status = "neutral"
    if higher_is_better is not None and abs(pct) >= THRESHOLD:
        improved = (diff > 0) == higher_is_better
        status = "good" if improved else "bad"
    return round(diff, 2), round(pct, 1), status


def _compare_block(a, b):
    out = []
    for key, name, unit, hib in _METRICS:
        av, bv = float(a.get(key, 0) or 0), float(b.get(key, 0) or 0)
        diff, pct, status = _delta(av, bv, hib)
        out.append({"metric": name, "key": key, "unit": unit,
                    "a": av, "b": bv, "diff": diff, "pct": pct, "status": status})
    return out


def _txn_verdict(block):
    bad = [m for m in block if m["key"] in _KEY_METRICS and m["status"] == "bad"]
    good = [m for m in block if m["key"] in _KEY_METRICS and m["status"] == "good"]
    if bad:
        worst = max(abs(m["pct"]) for m in bad)
        return "regression", worst
    if good:
        return "improvement", max(abs(m["pct"]) for m in good)
    return "stable", 0.0


def compare(stats_a, stats_b, name_a, name_b):
    overall = _compare_block(stats_a.get("overall", {}), stats_b.get("overall", {}))

    txn_a = {t["label"]: t for t in stats_a.get("transactions", [])}
    txn_b = {t["label"]: t for t in stats_b.get("transactions", [])}
    labels = set(txn_a) | set(txn_b)

    transactions = []
    for lbl in labels:
        a, b = txn_a.get(lbl), txn_b.get(lbl)
        if a and b:
            presence, block = "both", _compare_block(a, b)
        elif a:
            presence, block = "removed", _compare_block(a, {})
        else:
            presence, block = "added", _compare_block({}, b)
        verdict, severity = _txn_verdict(block)
        transactions.append({"label": lbl, "presence": presence, "metrics": block,
                             "verdict": verdict, "severity": severity})

    order = {"regression": 0, "improvement": 1, "stable": 2}
    transactions.sort(key=lambda t: (order[t["verdict"]], -t["severity"], t["label"].lower()))

    regressions = [t for t in transactions if t["verdict"] == "regression"]
    improvements = [t for t in transactions if t["verdict"] == "improvement"]
    worst = max(regressions, key=lambda t: t["severity"], default=None)
    summary = {
        "total": len(transactions),
        "regressions": len(regressions),
        "improvements": len(improvements),
        "stable": len(transactions) - len(regressions) - len(improvements),
        "verdict": "FAIL" if regressions else "PASS",
        "worst_label": worst["label"] if worst else None,
        "worst_pct": round(worst["severity"], 1) if worst else 0.0,
    }
    return {"name_a": name_a, "name_b": name_b, "summary": summary,
            "overall": overall, "transactions": transactions}
