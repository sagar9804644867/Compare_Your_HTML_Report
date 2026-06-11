"""
JMeter Performance Utility — Streamlit app.

Tab 1: build an HTML report from raw .jtl or a summary .csv, with Apdex + SLA.
Tab 2: compare two reports. Inputs can be .html (this tool / JMeter dashboard /
       plugin / Aggregate export), .csv (summary), or raw .jtl.
"""

import streamlit as st

from src.jtl_parser import load_many, compute_statistics, load_csv_any
from src.report_generator import generate_html_report
from src.html_comparator import extract_stats_from_upload, compare
from src.comparison_report import generate_comparison_html

st.set_page_config(page_title="JMeter Performance Utility", page_icon="📊", layout="wide")
st.session_state.setdefault("generated", [])  # [(name, html)]

st.title("📊 JMeter Performance Utility")
st.caption("Convert JTL/CSV results into rich HTML reports and compare two reports for regressions.")

tab_gen, tab_cmp = st.tabs(["① Build HTML Report", "② Compare Reports"])

# --------------------------------------------------------------------------- #
# Tab 1
# --------------------------------------------------------------------------- #
with tab_gen:
    st.subheader("Build an HTML report")
    st.write(
        "Upload raw JMeter `.jtl` result file(s) — *or* a Summary/Aggregate `.csv` export. "
        "Multiple `.jtl` files are merged (useful for distributed runs)."
    )
    files = st.file_uploader(
        "Upload .jtl / .csv / .xml", type=["jtl", "csv", "xml"],
        accept_multiple_files=True, key="gen_upload",
    )
    c1, c2, c3 = st.columns(3)
    title = c1.text_input("Report title", value="JMeter Performance Report")
    scenario = c2.text_input("Scenario name", value="Test Plan")
    apdex_t = c3.number_input("Apdex threshold T (ms)", min_value=50, max_value=20000,
                              value=500, step=50,
                              help="Requests ≤ T are 'satisfied'; ≤ 4T are 'tolerating'.")
    c4, c5, c6 = st.columns(3)
    err_verdict = c4.number_input("Verdict: fail if error % >", min_value=0.0, value=0.0, step=0.1,
                                  help="Overall PASS/FAIL. 0 = any error fails the run (JAAR-style).")
    with c5:
        st.write("SLA targets (optional)")
        sla_on = st.checkbox("Enable SLA pass/fail")
    sla = None
    if sla_on:
        sla = {
            "p90_ms": c6.number_input("90% Line target (ms)", min_value=0, value=2000, step=100),
            "error_pct": c6.number_input("Error % target", min_value=0.0, value=1.0, step=0.5),
        }

    if st.button("Generate HTML Report", type="primary", disabled=not files):
        try:
            with st.spinner("Parsing and building report…"):
                raw_files = [(f.name, f.getvalue()) for f in files]
                if len(raw_files) == 1 and raw_files[0][0].lower().endswith(".csv"):
                    stats = load_csv_any(raw_files[0][1], title.strip() or "Report", apdex_t, sla)
                else:
                    df = load_many(raw_files)
                    stats = compute_statistics(df, title.strip() or "Report", apdex_t, sla,
                                               scenario_name=scenario.strip() or "Test Plan",
                                               error_sla_pct=err_verdict)
                html = generate_html_report(stats)

            ov = stats["overall"]
            v = stats["meta"].get("verdict", "PASS")
            (st.error if v == "FAIL" else st.success)(
                f"Verdict: {v}" + (f" — {'; '.join(stats['meta'].get('verdict_reasons', []))}"
                                   if stats['meta'].get('verdict_reasons') else ""))
            cols = st.columns(6)
            cols[0].metric("Samples", f"{stats['meta']['total_samples']:,}")
            cols[1].metric("Avg (ms)", f"{ov['average']:,.0f}")
            cols[2].metric("90th (ms)", f"{ov['pct90']:,.0f}")
            cols[3].metric("Error %", f"{ov['error_pct']:.2f}%")
            cols[4].metric("Throughput/s", f"{ov['throughput']:,.2f}")
            cols[5].metric("Apdex", f"{ov.get('apdex',0):.3f}", ov.get("apdex_rating", ""))
            st.caption(f"Workload: {stats['meta'].get('classification',{}).get('kind','-')} · "
                       f"Duration {stats['meta'].get('duration_str','-')} · "
                       f"Peak VUs {stats['meta'].get('max_threads',0)}")

            fname = (title.strip() or "report").replace(" ", "_") + ".html"
            st.download_button("⬇️ Download HTML Report", data=html, file_name=fname,
                               mime="text/html", type="primary")
            st.session_state["generated"] = ([(fname, html)] + st.session_state["generated"])[:5]
            with st.expander("Preview report", expanded=True):
                st.components.v1.html(html, height=780, scrolling=True)
            st.info("This report is now selectable in the **Compare** tab.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not generate report: {exc}")

# --------------------------------------------------------------------------- #
# Tab 2
# --------------------------------------------------------------------------- #
with tab_cmp:
    st.subheader("Compare two reports")
    st.write(
        "**A = baseline**, **B = current**. Each side accepts an HTML report "
        "(this tool, JMeter HTML dashboard, plugin, or Aggregate export), a Summary "
        "`.csv`, or a raw `.jtl`. If a plugin's HTML can't be read, upload its `.csv` "
        "or the original `.jtl` instead."
    )
    generated_names = [n for n, _ in st.session_state["generated"]]
    gen_lookup = dict(st.session_state["generated"])

    def slot(letter):
        st.markdown(f"**Report {letter}**")
        src = "Upload file"
        if generated_names:
            src = st.radio(f"Source {letter}", ["Upload file", "Use a generated report"],
                           key=f"src_{letter}", horizontal=True)
        if src == "Use a generated report" and generated_names:
            pick = st.selectbox(f"Generated report {letter}", generated_names, key=f"pick_{letter}")
            return pick, gen_lookup[pick].encode("utf-8")
        up = st.file_uploader(f"Upload report {letter}", type=["html", "htm", "csv", "jtl", "xml"],
                              key=f"up_{letter}")
        return (up.name, up.getvalue()) if up else None

    ca, cb = st.columns(2)
    with ca:
        slot_a = slot("A")
    with cb:
        slot_b = slot("B")

    if st.button("Compare Reports", type="primary", disabled=not (slot_a and slot_b)):
        try:
            with st.spinner("Extracting statistics and comparing…"):
                sa = extract_stats_from_upload(slot_a[0], slot_a[1])
                sb = extract_stats_from_upload(slot_b[0], slot_b[1])
                cmp = compare(sa, sb, slot_a[0], slot_b[0])
                html = generate_comparison_html(cmp)

            s = cmp["summary"]
            (st.error if s["verdict"] == "FAIL" else st.success)(
                f"Verdict: {s['verdict']} — {s['regressions']} regression(s), "
                f"{s['improvements']} improvement(s)"
                + (f" · worst: {s['worst_label']} ({s['worst_pct']:+.1f}%)" if s["worst_label"] else ""))

            cols = st.columns(4)
            cols[0].metric("Transactions", s["total"])
            cols[1].metric("Regressions", s["regressions"])
            cols[2].metric("Improvements", s["improvements"])
            cols[3].metric("Stable", s["stable"])

            st.download_button("⬇️ Download Comparison Report", data=html,
                               file_name="comparison_report.html", mime="text/html", type="primary")
            with st.expander("Preview comparison", expanded=True):
                st.components.v1.html(html, height=640, scrolling=True)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not compare reports: {exc}")

st.divider()
st.caption(
    "Metrics include Apdex, p90/95/99/99.9, coefficient of variation (stability), "
    "latency/connect breakdown, throughput, and error-code breakdown — richest when "
    "you start from raw .jtl. Lower is better for response time/errors; higher for throughput/Apdex."
)
