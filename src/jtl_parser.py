"""
JTL / tabular parsing and statistics computation.

Supports:
  * Raw JMeter .jtl result files (CSV format, default since JMeter 3.x;
    best-effort XML).
  * Aggregate / Summary report exports (CSV) where each row is one transaction.

Produces statistics that mirror JMeter's Aggregate report and adds metrics a
performance engineer actually uses: Apdex, p99.9, latency/connect breakdown,
coefficient of variation (stability), throughput per minute, error breakdown by
response code, and optional SLA pass/fail.
"""

import io
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

DEFAULT_CSV_COLUMNS = [
    "timeStamp", "elapsed", "label", "responseCode", "responseMessage",
    "threadName", "dataType", "success", "failureMessage", "bytes",
    "sentBytes", "grpThreads", "allThreads", "URL", "Latency",
    "IdleTime", "Connect",
]

# Aggregate-CSV header aliases -> canonical key.
AGG_HEADER_MAP = {
    "label": "label", "transaction": "label", "sampler": "label", "requests": "label",
    "samples": "samples", "samples#": "samples", "count": "samples", "executions": "samples",
    "average": "average", "avg": "average",
    "median": "median", "med": "median",
    "90line": "pct90", "90": "pct90", "90thpct": "pct90", "p90": "pct90", "90pct": "pct90",
    "95line": "pct95", "95": "pct95", "95thpct": "pct95", "p95": "pct95", "95pct": "pct95",
    "99line": "pct99", "99": "pct99", "99thpct": "pct99", "p99": "pct99", "99pct": "pct99",
    "min": "min", "minimum": "min",
    "max": "max", "maximum": "max",
    "error": "error_pct", "errorpct": "error_pct", "errors": "error_pct",
    "throughput": "throughput", "tps": "throughput", "reqs": "throughput",
    "receivedkbsec": "received_kb_s", "kbsec": "received_kb_s", "received": "received_kb_s",
    "sentkbsec": "sent_kb_s",
}

APDEX_RATINGS = [
    (0.94, "Excellent"), (0.85, "Good"), (0.70, "Fair"),
    (0.50, "Poor"), (0.0, "Unacceptable"),
]

# Default metric template so downstream code can rely on keys existing.
_METRIC_KEYS = [
    "samples", "errors", "error_pct", "average", "median",
    "pct90", "pct95", "pct99", "pct999", "min", "max", "std", "cov",
    "throughput", "throughput_min", "received_kb_s", "sent_kb_s",
    "latency_avg", "connect_avg", "max_threads", "apdex", "apdex_rating",
]


def _blank_metrics() -> dict:
    d = {k: 0.0 for k in _METRIC_KEYS}
    d["apdex_rating"] = "n/a"
    d["error_codes"] = []
    return d


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# --------------------------------------------------------------------------- #
# Loading raw event data
# --------------------------------------------------------------------------- #
def _to_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def _read_csv_raw(text: str) -> pd.DataFrame:
    first = text.splitlines()[0] if text.strip() else ""
    if first.lower().startswith("timestamp"):
        return pd.read_csv(io.StringIO(text), low_memory=False)
    tmp = pd.read_csv(io.StringIO(text), header=None, low_memory=False)
    n = tmp.shape[1]
    cols = (DEFAULT_CSV_COLUMNS[:n] +
            [f"col{i}" for i in range(n - len(DEFAULT_CSV_COLUMNS))])
    tmp.columns = cols[:n]
    return tmp


def _read_xml(raw: bytes) -> pd.DataFrame:
    root = ET.fromstring(raw)
    rows = []
    for el in root.iter():
        if el.tag in ("httpSample", "sample"):
            a = el.attrib
            rows.append({
                "timeStamp": a.get("ts"), "elapsed": a.get("t"), "label": a.get("lb"),
                "responseCode": a.get("rc"), "responseMessage": a.get("rm"),
                "success": a.get("s"), "bytes": a.get("by"), "sentBytes": a.get("sby"),
                "allThreads": a.get("na"), "Latency": a.get("lt"), "Connect": a.get("ct"),
            })
    if not rows:
        raise ValueError("No <sample>/<httpSample> elements found in XML JTL.")
    return pd.DataFrame(rows)


def load_jtl(raw: bytes) -> pd.DataFrame:
    """Load raw event-level JTL (CSV or XML) into a normalised DataFrame."""
    stripped = raw.lstrip()
    if stripped[:5] == b"<?xml" or stripped[:1] == b"<":
        df = _read_xml(raw)
    else:
        df = _read_csv_raw(raw.decode("utf-8", errors="replace"))

    for col in ["timeStamp", "elapsed", "bytes", "sentBytes", "allThreads",
                "grpThreads", "Latency", "Connect", "IdleTime"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "label" not in df.columns or "elapsed" not in df.columns:
        raise ValueError("Raw JTL must contain 'label' and 'elapsed' columns.")

    df = df.dropna(subset=["timeStamp", "elapsed"])
    df["success"] = _to_bool_series(df["success"]) if "success" in df.columns else True
    return df


def load_many(files: list[tuple[str, bytes]]) -> pd.DataFrame:
    frames = []
    for name, raw in files:
        try:
            frames.append(load_jtl(raw))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Failed to parse '{name}': {exc}") from exc
    return pd.concat(frames, ignore_index=True).sort_values("timeStamp").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Statistics from raw events
# --------------------------------------------------------------------------- #
def _apdex(elapsed: np.ndarray, t_ms: float) -> tuple[float, str]:
    n = len(elapsed)
    if n == 0 or t_ms <= 0:
        return 0.0, "n/a"
    satisfied = int(np.sum(elapsed <= t_ms))
    tolerating = int(np.sum((elapsed > t_ms) & (elapsed <= 4 * t_ms)))
    score = round((satisfied + tolerating / 2) / n, 3)
    rating = next(r for thr, r in APDEX_RATINGS if score >= thr)
    return score, rating


def _error_codes(g: pd.DataFrame, top: int = 5) -> list[dict]:
    fails = g[~g["success"]]
    if fails.empty or "responseCode" not in fails.columns:
        return []
    counts = fails["responseCode"].astype(str).value_counts().head(top)
    return [{"code": str(k), "count": int(v)} for k, v in counts.items()]


def _label_stats(g: pd.DataFrame, apdex_t: float) -> dict:
    d = _blank_metrics()
    elapsed = g["elapsed"].to_numpy(dtype=float)
    n = len(elapsed)
    errors = int((~g["success"]).sum())

    ts_min = g["timeStamp"].min()
    ts_max = (g["timeStamp"] + g["elapsed"]).max()
    duration_s = max((ts_max - ts_min) / 1000.0, 1e-9)

    avg = float(np.mean(elapsed))
    std = float(np.std(elapsed))
    apdex, rating = _apdex(elapsed, apdex_t)

    d.update({
        "samples": n, "errors": errors,
        "error_pct": round(errors / n * 100, 2) if n else 0.0,
        "average": round(avg, 1), "median": round(float(np.percentile(elapsed, 50)), 1),
        "pct90": round(float(np.percentile(elapsed, 90)), 1),
        "pct95": round(float(np.percentile(elapsed, 95)), 1),
        "pct99": round(float(np.percentile(elapsed, 99)), 1),
        "pct999": round(float(np.percentile(elapsed, 99.9)), 1),
        "min": round(float(np.min(elapsed)), 1), "max": round(float(np.max(elapsed)), 1),
        "std": round(std, 1), "cov": round(std / avg * 100, 1) if avg else 0.0,
        "throughput": round(n / duration_s, 2), "throughput_min": round(n / duration_s * 60, 1),
        "apdex": apdex, "apdex_rating": rating,
        "error_codes": _error_codes(g),
    })
    if "bytes" in g:
        d["received_kb_s"] = round(g["bytes"].sum() / 1024.0 / duration_s, 2)
    if "sentBytes" in g:
        d["sent_kb_s"] = round(g["sentBytes"].sum() / 1024.0 / duration_s, 2)
    if "Latency" in g and g["Latency"].notna().any():
        d["latency_avg"] = round(float(g["Latency"].mean()), 1)
    if "Connect" in g and g["Connect"].notna().any():
        d["connect_avg"] = round(float(g["Connect"].mean()), 1)
    if "allThreads" in g and g["allThreads"].notna().any():
        d["max_threads"] = int(g["allThreads"].max())
    return d


def _time_series(df: pd.DataFrame, interval: int = 60, max_points: int = 600) -> dict:
    """Bucket samples for trend charts. Default 60s intervals (JAAR-style)."""
    t0 = df["timeStamp"].min()
    rel_s = (df["timeStamp"] - t0) / 1000.0
    span = max(rel_s.max(), 1.0)
    if span / interval > max_points:
        interval = int(np.ceil(span / max_points))
    bucket = (rel_s // interval).astype(int)
    grouped = df.assign(_b=bucket).groupby("_b")
    times, clock, avg_rt, p90, tp, errs, thr = [], [], [], [], [], [], []
    for b, grp in grouped:
        off = int(b * interval)
        times.append(off)
        clock.append(int(t0 + off * 1000))  # absolute epoch ms for HH:mm:ss axis
        e = grp["elapsed"].to_numpy(dtype=float)
        avg_rt.append(round(float(np.mean(e)), 1))
        p90.append(round(float(np.percentile(e, 90)), 1))
        tp.append(round(len(grp) / interval, 2))
        errs.append(int((~grp["success"]).sum()))
        thr.append(int(grp["allThreads"].max()) if "allThreads" in grp and grp["allThreads"].notna().any() else 0)
    return {"interval_s": interval, "time_s": times, "clock_ms": clock,
            "avg_response_ms": avg_rt, "p90_ms": p90,
            "throughput_rps": tp, "errors": errs, "threads": thr}


def _slowest_requests(df: pd.DataFrame, t0: int, top: int = 10) -> list[dict]:
    cols = ["elapsed", "label", "timeStamp"]
    if "responseCode" in df.columns:
        cols.append("responseCode")
    top_df = df.nlargest(top, "elapsed")[cols]
    out = []
    for _, r in top_df.iterrows():
        out.append({
            "elapsed": int(r["elapsed"]), "label": str(r["label"]),
            "timestamp_s": round((int(r["timeStamp"]) - t0) / 1000.0, 1),
            "response_code": str(r.get("responseCode", "")),
        })
    return out


def _error_detail(df: pd.DataFrame, t0: int, limit: int = 50) -> list[dict]:
    fails = df[~df["success"]]
    if fails.empty:
        return []
    out = []
    for _, r in fails.head(limit).iterrows():
        out.append({
            "label": str(r["label"]),
            "response_code": str(r.get("responseCode", "")),
            "message": str(r.get("failureMessage", "") or r.get("responseMessage", "") or ""),
            "elapsed": int(r["elapsed"]),
            "timestamp_s": round((int(r["timeStamp"]) - t0) / 1000.0, 1),
        })
    return out


def _heatmap(df: pd.DataFrame, t0: int) -> dict:
    """Per-transaction p50/p90/p99 for each minute of the test."""
    rel_min = ((df["timeStamp"] - t0) / 60000.0).astype(int)
    work = df.assign(_min=rel_min)
    minutes = sorted(work["_min"].unique().tolist())
    # cap displayed minutes to keep the table readable
    if len(minutes) > 40:
        minutes = minutes[:40]
    buckets = []
    for label, g in work.groupby("label"):
        vals = []
        for m in minutes:
            cell = g[g["_min"] == m]
            if cell.empty:
                continue
            e = cell["elapsed"].to_numpy(dtype=float)
            vals.append({"minute": int(m), "p50": int(np.percentile(e, 50)),
                         "p90": int(np.percentile(e, 90)), "p99": int(np.percentile(e, 99))})
        buckets.append({"label": str(label), "values": vals})
    return {"minutes": minutes, "labels": [b["label"] for b in buckets], "buckets": buckets}


def _classify_workload(df: pd.DataFrame, meta: dict, overall: dict, series: dict) -> dict:
    """Heuristic workload classification (load / stress / soak / spike / smoke)."""
    dur_min = meta["duration_s"] / 60.0
    vu = meta["max_threads"]
    samples = meta["total_samples"]
    threads = [t for t in series["threads"] if t >= 0]
    tps = series["throughput_rps"]

    # thread profile
    if threads and max(threads) > 0:
        rising = threads[-1] > threads[0] and max(threads) > min(threads) + 1
        thread_cov = (np.std(threads) / np.mean(threads) * 100) if np.mean(threads) else 0
    else:
        rising, thread_cov = False, 0
    tp_cov = (np.std(tps) / np.mean(tps) * 100) if tps and np.mean(tps) else 0

    if samples < 50 or dur_min < 2:
        kind, why = "Smoke / Sanity Test", "Very short run with few samples — validates the script, not capacity."
    elif rising:
        kind, why = "Stress / Ramp-up Test", "Concurrency increases over the run to find the breaking point."
    elif tp_cov > 60:
        kind, why = "Spike Test", "Throughput swings sharply, indicating bursty / spike load."
    elif dur_min >= 30:
        kind, why = "Endurance / Soak Test", "Sustained steady load over a long duration — checks for leaks and degradation."
    else:
        kind, why = "Load Test", "Steady concurrency for a moderate duration at target load."

    signals = [
        ("Duration", f"{int(dur_min)} min {int(meta['duration_s'] % 60)} s"),
        ("Peak virtual users", f"{vu}"),
        ("Total samples", f"{samples:,}"),
        ("Avg throughput", f"{overall['throughput']:.2f} req/s"),
        ("Throughput variability (CoV)", f"{tp_cov:.0f}%"),
        ("Thread profile", "ramping up" if rising else "constant"),
    ]
    return {"kind": kind, "reasoning": why, "signals": signals}


def _verdict(stats: dict, error_sla: float) -> None:
    """Overall PASS/FAIL: fails on SLA breach (if set) or error rate over threshold."""
    failed_reasons = []
    if stats["meta"].get("sla_failed", 0):
        failed_reasons.append(f"{stats['meta']['sla_failed']} transaction(s) breached SLA")
    if stats["overall"]["error_pct"] > error_sla:
        failed_reasons.append(f"error rate {stats['overall']['error_pct']:.2f}% > {error_sla:.2f}%")
    stats["meta"]["verdict"] = "FAIL" if failed_reasons else "PASS"
    stats["meta"]["verdict_reasons"] = failed_reasons


def _apply_sla(stats: dict, sla: dict | None) -> None:
    if not sla:
        return
    p90_t = sla.get("p90_ms")
    err_t = sla.get("error_pct")

    def verdict(row):
        breaches = []
        if p90_t and row.get("pct90", 0) > p90_t:
            breaches.append(f"p90 {row['pct90']:.0f}ms > {p90_t:.0f}ms")
        if err_t is not None and row.get("error_pct", 0) > err_t:
            breaches.append(f"err {row['error_pct']:.2f}% > {err_t:.2f}%")
        row["sla_pass"] = not breaches
        row["sla_breaches"] = breaches

    verdict(stats["overall"])
    for t in stats["transactions"]:
        verdict(t)
    stats["meta"]["sla"] = sla
    stats["meta"]["sla_failed"] = sum(1 for t in stats["transactions"] if not t["sla_pass"])


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {sec}s"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def compute_statistics(df: pd.DataFrame, title: str = "Performance Report",
                       apdex_t: float = 500.0, sla: dict | None = None,
                       scenario_name: str = "Test Plan",
                       error_sla_pct: float = 0.0) -> dict:
    import datetime as _dt

    overall = _label_stats(df, apdex_t)
    transactions = []
    for label, grp in df.groupby("label", sort=False):
        row = {"label": str(label)}
        row.update(_label_stats(grp, apdex_t))
        transactions.append(row)
    transactions.sort(key=lambda r: r["label"].lower())

    ts_min = int(df["timeStamp"].min())
    ts_max = int((df["timeStamp"] + df["elapsed"]).max())
    duration_s = round((ts_max - ts_min) / 1000.0, 1)
    start_dt = _dt.datetime.fromtimestamp(ts_min / 1000)
    end_dt = _dt.datetime.fromtimestamp(ts_max / 1000)

    series = _time_series(df)
    meta = {
        "title": title, "scenario_name": scenario_name,
        "total_samples": overall["samples"],
        "duration_s": duration_s, "duration_str": _fmt_duration(duration_s),
        "start_ms": ts_min, "end_ms": ts_max,
        "start_str": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "end_str": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "transaction_count": len(transactions),
        "apdex_threshold_ms": apdex_t,
        "max_threads": overall["max_threads"],
    }
    stats = {
        "schema": "perf-utility/v3", "meta": meta,
        "overall": overall, "transactions": transactions, "series": series,
        "slowest": _slowest_requests(df, ts_min),
        "error_detail": _error_detail(df, ts_min),
        "heatmap": _heatmap(df, ts_min),
    }
    _apply_sla(stats, sla)
    stats["meta"]["classification"] = _classify_workload(df, meta, overall, series)
    _verdict(stats, error_sla_pct)
    return stats


# --------------------------------------------------------------------------- #
# Statistics from an aggregate/summary table (CSV or HTML)
# --------------------------------------------------------------------------- #
def _num(text) -> float:
    m = re.search(r"-?[\d,]+\.?\d*", str(text).replace(",", ""))
    return float(m.group()) if m else 0.0


def build_stats_from_summary(rows: list[dict], title: str, apdex_t: float = 500.0,
                             sla: dict | None = None) -> dict:
    """Assemble a stats dict from pre-aggregated per-transaction rows.

    `rows` items may contain any subset of canonical metric keys plus 'label'.
    Missing metrics default to 0. (Apdex/latency/error-codes aren't recoverable
    from a summary, so they stay blank.)
    """
    txns = []
    total_row = None
    for r in rows:
        rec = _blank_metrics()
        rec["label"] = str(r.get("label", "")).strip()
        for k in _METRIC_KEYS:
            if k in r and r[k] not in (None, ""):
                rec[k] = r[k] if k in ("apdex_rating",) else _num(r[k])
        if not rec["label"]:
            continue
        if _norm(rec["label"]) in ("total", "all"):
            total_row = rec
        else:
            txns.append(rec)
    if not txns and total_row is None:
        raise ValueError("No transaction rows found in summary data.")

    if total_row is None:
        total = sum(t["samples"] for t in txns) or 1
        def w(key):
            return round(sum(t[key] * t["samples"] for t in txns) / total, 1)
        total_row = _blank_metrics()
        total_row.update({
            "label": "TOTAL", "samples": int(total),
            "average": w("average"), "median": w("median"),
            "pct90": w("pct90"), "pct95": w("pct95"), "pct99": w("pct99"),
            "min": min((t["min"] for t in txns), default=0),
            "max": max((t["max"] for t in txns), default=0),
            "error_pct": w("error_pct"),
            "throughput": round(sum(t["throughput"] for t in txns), 2),
            "received_kb_s": round(sum(t["received_kb_s"] for t in txns), 2),
        })

    txns.sort(key=lambda r: r["label"].lower())
    stats = {
        "schema": "summary/v3",
        "meta": {"title": title, "scenario_name": title,
                 "total_samples": int(total_row["samples"]),
                 "duration_s": 0, "duration_str": "n/a",
                 "start_str": "n/a", "end_str": "n/a",
                 "transaction_count": len(txns),
                 "apdex_threshold_ms": apdex_t, "max_threads": 0,
                 "source": "summary export (limited metrics: no Apdex/latency/error-code/time-series detail)"},
        "overall": total_row, "transactions": txns, "series": None,
        "slowest": [], "error_detail": [], "heatmap": None,
    }
    _apply_sla(stats, sla)
    stats["meta"]["classification"] = {
        "kind": "Unknown (summary input)",
        "reasoning": "Workload classification needs event-level data; upload the raw .jtl for this.",
        "signals": [("Transactions", str(len(txns))),
                    ("Total samples", f"{int(total_row['samples']):,}")],
    }
    _verdict(stats, 0.0)
    return stats


def _aggregate_csv_to_rows(df: pd.DataFrame) -> list[dict]:
    mapping = {}
    for col in df.columns:
        key = AGG_HEADER_MAP.get(_norm(str(col)))
        if key:
            mapping[col] = key
    if "label" not in mapping.values():
        raise ValueError("Aggregate CSV has no recognizable 'Label' column.")
    rows = []
    for _, r in df.iterrows():
        rec = {mapping[c]: r[c] for c in mapping}
        rows.append(rec)
    return rows


def is_aggregate_csv(text: str) -> bool:
    header = text.splitlines()[0].lower() if text.strip() else ""
    if header.startswith("timestamp"):
        return False  # raw events
    norm_cols = {_norm(c) for c in header.split(",")}
    return bool(norm_cols & {"label", "transaction", "sampler"}) and \
        bool(norm_cols & {"average", "avg"})


def load_csv_any(raw: bytes, title: str, apdex_t: float = 500.0,
                 sla: dict | None = None) -> dict:
    """Route a .csv: aggregate summary -> summary stats; else raw events."""
    text = raw.decode("utf-8", errors="replace")
    if is_aggregate_csv(text):
        df = pd.read_csv(io.StringIO(text), low_memory=False)
        return build_stats_from_summary(_aggregate_csv_to_rows(df), title, apdex_t, sla)
    df = load_jtl(raw)
    return compute_statistics(df, title, apdex_t, sla)
