"""
Report generator for PyScreen benchmark comparisons.
Produces human-readable comparison reports from benchmark results.
"""
import json
import os
from datetime import datetime


def generate_comparison_report(results: list, output_dir: str = "result") -> str:
    """
    Generate a formatted comparison report from benchmark results.

    Args:
        results: List of BenchmarkResult.to_dict() dictionaries
        output_dir: Directory to save the report

    Returns:
        The report as a string
    """
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("  PyScreen Benchmark Comparison Report")
    report_lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("=" * 80)
    report_lines.append("")

    # Group results by dataset
    datasets = {}
    for r in results:
        ds = r["dataset"]
        if ds not in datasets:
            datasets[ds] = {}
        datasets[ds][r["mode"]] = r

    # Per-dataset comparison
    for dataset, modes in datasets.items():
        report_lines.append(f"\n{'-' * 80}")
        report_lines.append(f"  Dataset: {dataset.upper()}")
        report_lines.append(f"{'-' * 80}")

        screenshot_data = modes.get("screenshots")
        video_data = modes.get("video")

        headers = ["Metric", "Screenshots", "Video", "Winner"]
        rows = []

        # Collect metrics for comparison
        metrics = _extract_comparison_metrics(screenshot_data, video_data)
        for metric_name, ss_val, vid_val, winner in metrics:
            rows.append([metric_name, ss_val, vid_val, winner])

        # Print table
        col_widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(4)]
        header_line = " | ".join(str(headers[i]).ljust(col_widths[i]) for i in range(4))
        sep_line = "-+-".join("-" * col_widths[i] for i in range(4))

        report_lines.append(f"\n  {header_line}")
        report_lines.append(f"  {sep_line}")
        for row in rows:
            line = " | ".join(str(row[i]).ljust(col_widths[i]) for i in range(4))
            report_lines.append(f"  {line}")

    # Overall summary
    report_lines.append(f"\n{'=' * 80}")
    report_lines.append("  OVERALL SUMMARY")
    report_lines.append(f"{'=' * 80}")

    ss_wins, vid_wins = _count_wins(results)
    report_lines.append(f"\n  Screenshots approach wins: {ss_wins}")
    report_lines.append(f"  Video approach wins:       {vid_wins}")

    if ss_wins > vid_wins:
        report_lines.append("\n  >> RECOMMENDATION: Screenshots approach is better overall.")
    elif vid_wins > ss_wins:
        report_lines.append("\n  >> RECOMMENDATION: Video approach is better overall.")
    else:
        report_lines.append("\n  >> RESULT: Both approaches are comparable.")

    report_lines.append("")
    report_lines.append("  Notes:")
    report_lines.append("  - 'Winner' is determined by: lower time, lower cost, lower memory = better")
    report_lines.append("  - Token usage indicates API efficiency (fewer tokens = better)")
    report_lines.append("  - Output length may indicate analysis detail (more = potentially better)")
    report_lines.append("")

    report = "\n".join(report_lines)

    # Save report
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "benchmark_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    # Save raw JSON metrics
    json_path = os.path.join(output_dir, "benchmark_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "results": results,
        }, f, indent=2)

    return report


def _extract_comparison_metrics(ss_data, vid_data):
    """Extract comparable metrics from two benchmark results."""
    metrics = []

    def _safe_get(data, *keys, default="N/A"):
        if data is None:
            return default
        val = data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, default)
            else:
                return default
        return val

    def _compare_lower_wins(name, ss_val, vid_val, unit=""):
        """Lower value wins."""
        ss_str = f"{ss_val}{unit}" if ss_val != "N/A" else "N/A"
        vid_str = f"{vid_val}{unit}" if vid_val != "N/A" else "N/A"
        if ss_val == "N/A" or vid_val == "N/A":
            winner = "N/A"
        elif ss_val < vid_val:
            winner = "Screenshots"
        elif vid_val < ss_val:
            winner = "Video"
        else:
            winner = "Tie"
        return (name, ss_str, vid_str, winner)

    def _compare_higher_wins(name, ss_val, vid_val, unit=""):
        """Higher value wins."""
        ss_str = f"{ss_val}{unit}" if ss_val != "N/A" else "N/A"
        vid_str = f"{vid_val}{unit}" if vid_val != "N/A" else "N/A"
        if ss_val == "N/A" or vid_val == "N/A":
            winner = "N/A"
        elif ss_val > vid_val:
            winner = "Screenshots"
        elif vid_val > ss_val:
            winner = "Video"
        else:
            winner = "Tie"
        return (name, ss_str, vid_str, winner)

    # Frames
    ss_frames = _safe_get(ss_data, "num_frames")
    vid_frames = _safe_get(vid_data, "num_frames")
    metrics.append(("Frames Processed", str(ss_frames), str(vid_frames), "-"))

    # Total time
    ss_time = _safe_get(ss_data, "total_time_seconds")
    vid_time = _safe_get(vid_data, "total_time_seconds")
    metrics.append(_compare_lower_wins("Total Time", ss_time, vid_time, "s"))

    # Phase timings
    for phase_name in ["frame_loading", "ocr_processing", "gemini_analysis"]:
        ss_phase_time = "N/A"
        vid_phase_time = "N/A"
        if ss_data:
            for p in ss_data.get("phases", []):
                if p.get("name") == phase_name:
                    ss_phase_time = p["duration_seconds"]
        if vid_data:
            for p in vid_data.get("phases", []):
                if p.get("name") == phase_name:
                    vid_phase_time = p["duration_seconds"]
        label = phase_name.replace("_", " ").title()
        metrics.append(_compare_lower_wins(f"  {label}", ss_phase_time, vid_phase_time, "s"))

    # API metrics
    ss_api_time = _safe_get(ss_data, "api_metrics", "request_time_seconds")
    vid_api_time = _safe_get(vid_data, "api_metrics", "request_time_seconds")
    metrics.append(_compare_lower_wins("API Latency", ss_api_time, vid_api_time, "s"))

    ss_input_tok = _safe_get(ss_data, "api_metrics", "input_tokens")
    vid_input_tok = _safe_get(vid_data, "api_metrics", "input_tokens")
    metrics.append(_compare_lower_wins("Input Tokens", ss_input_tok, vid_input_tok))

    ss_output_tok = _safe_get(ss_data, "api_metrics", "output_tokens")
    vid_output_tok = _safe_get(vid_data, "api_metrics", "output_tokens")
    metrics.append(("Output Tokens", str(ss_output_tok), str(vid_output_tok), "-"))

    ss_cost = _safe_get(ss_data, "api_metrics", "estimated_cost_usd")
    vid_cost = _safe_get(vid_data, "api_metrics", "estimated_cost_usd")
    metrics.append(_compare_lower_wins("Est. Cost", ss_cost, vid_cost, " USD"))

    # Memory
    ss_mem = _safe_get(ss_data, "peak_memory_mb")
    vid_mem = _safe_get(vid_data, "peak_memory_mb")
    metrics.append(_compare_lower_wins("Peak Memory", ss_mem, vid_mem, " MB"))

    # Output quality proxy
    ss_out_len = _safe_get(ss_data, "analysis_output_length")
    vid_out_len = _safe_get(vid_data, "analysis_output_length")
    metrics.append(_compare_higher_wins("Analysis Length", ss_out_len, vid_out_len, " chars"))

    # Success
    ss_success = _safe_get(ss_data, "success")
    vid_success = _safe_get(vid_data, "success")
    metrics.append(("Success", str(ss_success), str(vid_success), "-"))

    return metrics


def _count_wins(results):
    """Count wins for each approach across all datasets."""
    ss_wins = 0
    vid_wins = 0

    datasets = {}
    for r in results:
        ds = r["dataset"]
        if ds not in datasets:
            datasets[ds] = {}
        datasets[ds][r["mode"]] = r

    for dataset, modes in datasets.items():
        ss = modes.get("screenshots")
        vid = modes.get("video")
        if not ss or not vid:
            continue

        # Compare time
        if ss.get("total_time_seconds", float('inf')) < vid.get("total_time_seconds", float('inf')):
            ss_wins += 1
        elif vid.get("total_time_seconds", float('inf')) < ss.get("total_time_seconds", float('inf')):
            vid_wins += 1

        # Compare cost
        ss_cost = ss.get("api_metrics", {}).get("estimated_cost_usd", float('inf'))
        vid_cost = vid.get("api_metrics", {}).get("estimated_cost_usd", float('inf'))
        if ss_cost < vid_cost:
            ss_wins += 1
        elif vid_cost < ss_cost:
            vid_wins += 1

        # Compare memory
        if ss.get("peak_memory_mb", float('inf')) < vid.get("peak_memory_mb", float('inf')):
            ss_wins += 1
        elif vid.get("peak_memory_mb", float('inf')) < ss.get("peak_memory_mb", float('inf')):
            vid_wins += 1

    return ss_wins, vid_wins
