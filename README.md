# JMeter Performance Utility

A Streamlit app for two performance-engineering chores:

1. **Build an HTML report** from raw JMeter `.jtl` results *or* a Summary/Aggregate
   `.csv` export — a self-contained HTML report with KPIs, trend charts, and a full
   per-transaction statistics table.
2. **Compare two reports** (A = baseline, B = current) and get a comparison report
   that flags regressions/improvements per transaction with an overall PASS/FAIL verdict.

## Metrics (what a perf engineer actually wants)

Beyond the standard JMeter aggregate columns, reports include:

- **Apdex** with configurable threshold T and rating (Excellent → Unacceptable)
- **Percentiles** 90 / 95 / 99 / **99.9**
- **Coefficient of variation (CoV)** — response-time stability (lower = more consistent)
- **Latency (TTFB) and Connect-time** averages (from raw `.jtl`)
- **Throughput** per second and per minute
- **Error breakdown by response code**
- **Active-threads (concurrency) and errors-over-time** charts
- **SLA pass/fail** against optional 90%-line and error-% targets

> Richest output comes from raw `.jtl` (Apdex, latency, error codes, CoV all need
> event-level data). Summary `.csv` / external HTML give the columns they contain.

## Accepted inputs

| Where | Formats |
|---|---|
| Build report | raw `.jtl` (CSV/XML), Summary/Aggregate `.csv` |
| Compare (each side) | `.html` (this tool, JMeter HTML dashboard, plugin, Aggregate export), `.csv`, raw `.jtl` |

### HTML compatibility

The comparator extracts stats in this order: (1) JSON embedded by this tool,
(2) JSON/JS data inside any `<script>` block — covers JMeter dashboard
`statistics.json`-style data and many plugin reports that render their table
client-side, (3) a static aggregate-style `<table>`. If a specific plugin's HTML
still can't be read, upload its `.csv` export or the original `.jtl` instead.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

Push to GitHub → https://share.streamlit.io → New app → main file `app.py`.

## Layout

```
app.py                    Streamlit UI (build + compare)
src/
  jtl_parser.py           JTL/CSV parsing, statistics engine, Apdex/SLA, summary assembly
  report_generator.py     self-contained HTML report (embeds stats JSON)
  html_comparator.py      multi-format extraction + comparison/verdict logic
  comparison_report.py    comparison HTML renderer
samples/                  example .jtl files and generated reports
```

## Notes

- Percentiles use numpy linear interpolation (marginal difference vs JMeter's exact method).
- Trend charts use Chart.js via CDN; tables and comparison output work offline.
