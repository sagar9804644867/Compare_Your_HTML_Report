"""
JTL parsing and statistics computation.

Handles JMeter .jtl result files in CSV format (the default since JMeter 3.x)
and best-effort XML format. Produces aggregate statistics that mirror JMeter's
Aggregate / Summary report, plus time-series data for charts.
"""

import io
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

# Canonical JMeter CSV column order (used when a header row is absent).
DEFAULT_CSV_COLUMNS = [
    "timeStamp", "elapsed", "label", "responseCode", "responseMessage",
    "threadName", "dataType", "success", "failureMessage", "bytes",
    "sentBytes", "grpThreads", "allThreads", "URL", "Latency",
    "IdleTime", "Connect",
]


def _to_bool_series(series: pd.Series) -> pd.Series:
    """Normalise the 'success' column (true/false strings, 1/0, bools) to bool."""
    if series.dtype == bool:
        return series
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes"])
    )


def _read_csv(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8", errors="replace")
    first_line = text.splitlines()[0] if text.strip() else ""
    has_header = first_line.lower().startswith("timestamp")

    if has_header:
        df = pd.read_csv(io.StringIO(text), low_memory=False)
    else:
        # Headerless JTL: assign canonical names for the columns we got.
        tmp = pd.read_csv(io.StringIO(text), header=None, low_memory=False)
        ncols = tmp.shape[1]
        cols = DEFAULT_CSV_COLUMNS[:ncols] + [
            f"col{i}" for i in range(ncols - len(DEFAULT_CSV_COLUMNS))
        ]
        tmp.columns = cols[:ncols]
        df = tmp
    return df


def _read_xml(raw: bytes) -> pd.DataFrame:
    """Best-effort parse of XML-format JTL (<httpSample>/<sample> elements)."""
    root = ET.fromstring(raw)
    rows = []
    for el in root.iter():
        if el.tag in ("httpSample", "sample"):
            a = el.attrib
            rows.append({
                "timeStamp": a.get("ts"),
                "elapsed": a.get("t"),
                "label": a.get("lb"),
                "responseCode": a.get("rc"),
                "responseMessage": a.get("rm"),
                "threadName": a.get("tn"),
                "dataType": a.get("dt"),
                "success": a.get("s"),
                "bytes": a.get("by"),
                "sentBytes": a.get("sby"),
                "allThreads": a.get("na"),
                "Latency": a.get("lt"),
                "Connect": a.get("ct"),
            })
    if not rows:
        raise ValueError("No <sample>/<httpSample> elements found in XML JTL.")
    return pd.DataFrame(rows)


def load_jtl(raw: bytes) -> pd.DataFrame:
    """Load a single JTL file (bytes) into a normalised DataFrame."""
    stripped = raw.lstrip()
    if stripped[:5] == b"<?xml" or stripped[:1] == b"<":
        df = _read_xml(raw)
    else:
        df = _read_csv(raw)

    # Coerce numeric columns.
    for col in ["timeStamp", "elapsed", "bytes", "sentBytes", "allThreads",
                "grpThreads", "Latency", "Connect", "IdleTime"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "label" not in df.columns:
        raise ValueError("JTL is missing the 'label' column; cannot parse.")
    if "elapsed" not in df.columns:
        raise ValueError("JTL is missing the 'elapsed' column; cannot parse.")

    df = df.dropna(subset=["timeStamp", "elapsed"])
    if "success" in df.columns:
        df["success"] = _to_bool_series(df["success"])
    else:
        df["success"] = True

    return df


def load_many(files: list[tuple[str, bytes]]) -> pd.DataFrame:
    """Merge multiple JTL files (e.g. distributed test outputs) into one frame."""
    frames = []
    for name, raw in files:
        try:
            frames.append(load_jtl(raw))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Failed to parse '{name}': {exc}") from exc
    merged = pd.concat(frames, ignore_index=True)
    return merged.sort_values("timeStamp").reset_index(drop=True)


def _label_stats(g: pd.DataFrame) -> dict:
    elapsed = g["elapsed"].to_numpy(dtype=float)
    n = len(elapsed)
    errors = int((~g["success"]).sum())

    ts_min = g["timeStamp"].min()
    ts_max = (g["timeStamp"] + g["elapsed"]).max()
    duration_s = max((ts_max - ts_min) / 1000.0, 1e-9)

    received_kb = g["bytes"].sum() / 1024.0 if "bytes" in g else 0.0
    sent_kb = g["sentBytes"].sum() / 1024.0 if "sentBytes" in g else 0.0

    return {
        "samples": n,
        "errors": errors,
        "error_pct": round(errors / n * 100, 2) if n else 0.0,
        "average": round(float(np.mean(elapsed)), 1),
        "median": round(float(np.percentile(elapsed, 50)), 1),
        "pct90": round(float(np.percentile(elapsed, 90)), 1),
        "pct95": round(float(np.percentile(elapsed, 95)), 1),
        "pct99": round(float(np.percentile(elapsed, 99)), 1),
        "min": round(float(np.min(elapsed)), 1),
        "max": round(float(np.max(elapsed)), 1),
        "std": round(float(np.std(elapsed)), 1),
        "throughput": round(n / duration_s, 2),
        "received_kb_s": round(received_kb / duration_s, 2),
        "sent_kb_s": round(sent_kb / duration_s, 2),
    }


def _time_series(df: pd.DataFrame, max_points: int = 400) -> dict:
    """Bucket samples over time for trend charts. Interval auto-scales."""
    t0 = df["timeStamp"].min()
    rel_s = (df["timeStamp"] - t0) / 1000.0
    span = max(rel_s.max(), 1.0)
    interval = max(1, int(np.ceil(span / max_points)))
    bucket = (rel_s // interval).astype(int)

    grouped = df.assign(_b=bucket).groupby("_b")
    labels, avg_rt, throughput, errs = [], [], [], []
    for b, grp in grouped:
        labels.append(int(b * interval))
        avg_rt.append(round(float(grp["elapsed"].mean()), 1))
        throughput.append(round(len(grp) / interval, 2))
        errs.append(int((~grp["success"]).sum()))
    return {
        "interval_s": interval,
        "time_s": labels,
        "avg_response_ms": avg_rt,
        "throughput_rps": throughput,
        "errors": errs,
    }


def compute_statistics(df: pd.DataFrame, title: str = "Performance Report") -> dict:
    """Return a structured stats dict: meta, overall, per-transaction, time-series."""
    overall = _label_stats(df)

    transactions = []
    for label, grp in df.groupby("label", sort=False):
        row = {"label": str(label)}
        row.update(_label_stats(grp))
        transactions.append(row)
    transactions.sort(key=lambda r: r["label"].lower())

    ts_min = int(df["timeStamp"].min())
    ts_max = int((df["timeStamp"] + df["elapsed"]).max())

    return {
        "schema": "perf-utility/v1",
        "meta": {
            "title": title,
            "total_samples": overall["samples"],
            "duration_s": round((ts_max - ts_min) / 1000.0, 1),
            "start_ms": ts_min,
            "end_ms": ts_max,
            "transaction_count": len(transactions),
        },
        "overall": overall,
        "transactions": transactions,
        "series": _time_series(df),
    }
