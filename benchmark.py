#!/usr/bin/env python3
"""
PyScreen LLM Benchmarking Tool v4
==================================
Benchmarks local LLMs for security context extraction quality.
Supports temperature sweeps to find optimal settings per model.

Results layout:
  benchmark_results/
    ocr_cache.json                                      # Shared OCR cache
    ocr_input.txt                                       # What all models receive
    model_comparison.md                                 # Cross-model comparison
    <model_name>/
      t0.0_report.md                                   # Report at temp=0.0
      t0.3_report.md                                   # Report at temp=0.3
      t0.7_report.md                                   # Report at temp=0.7
      metrics.json                                     # All metrics for this model
      best_temperature.txt                             # Which temp was best
"""

import os
import re
import json
import time
import argparse
import requests
from datetime import datetime

from utils.frames import get_frames_from_ares_dir
from utils.text_compute import text_compute
from utils.llm_analyze import analyze_screens


def detect_model_name(host="http://127.0.0.1:8001", api_key="my_secret_token"):
    """Query llama-server to find the currently loaded model."""
    try:
        resp = requests.get(
            f"{host}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if "data" in data and len(data["data"]) > 0:
            raw = data["data"][0].get("id", "unknown")
        elif "models" in data and len(data["models"]) > 0:
            raw = data["models"][0].get("name", "unknown")
        else:
            return "unknown"

        basename = os.path.basename(raw)
        name = os.path.splitext(basename)[0]
        name = re.sub(r'[^\w\-\.]', '_', name)
        return name

    except Exception as e:
        print(f"    Warning: Could not detect model name: {e}")
        return "unknown"


def load_ocr_cache(cache_path):
    if os.path.exists(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_ocr_cache(cache_path, screen_data, state_graph):
    cache = {"screen_data": screen_data, "state_graph": state_graph}
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)


def save_ocr_input(results_dir, screen_data, state_graph):
    """Save the exact text fed to the model so the user can audit it."""
    out_path = os.path.join(results_dir, "ocr_input.txt")
    if os.path.exists(out_path):
        return
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("OCR EXTRACTED TEXT (This is what all models receive as input)\n")
        f.write("=" * 80 + "\n\n")
        for screen in screen_data:
            f.write(f"--- Screen: {screen['filename']} ---\n")
            f.write(screen.get("extracted_text", "[No text extracted]"))
            f.write("\n\n")
        f.write("=" * 80 + "\n")
        f.write("STATE TRANSITION GRAPH (Also sent to all models)\n")
        f.write("=" * 80 + "\n\n")
        f.write(json.dumps(state_graph, indent=2))
        f.write("\n")


def score_report(report):
    """Heuristic quality scoring for a JSON context extraction report."""
    score = 0
    try:
        # 1. Valid JSON (0-40 pts)
        data = json.loads(report)
        score += 40
        
        # 2. Key Structure Checks (0-30 pts)
        if "app_summary" in data:
            score += 10
        if "workflows" in data or "core_workflows" in data:
            score += 10
        if "screen_contexts" in data:
            score += 10
            
        # 3. Content Depth (0-30 pts)
        text_dump = json.dumps(data).lower()
        if "redreader" in text_dump or "red reader" in text_dump or "reddit" in text_dump:
            score += 10
            
        # Specificity — references actual state numbers/files
        import re as _re
        state_refs = len(_re.findall(r'state\s*\d+', text_dump, _re.IGNORECASE))
        score += min(state_refs * 2, 20)
            
    except json.JSONDecodeError:
        # Invalid JSON gets 0 base score, but we can check if it outputted anything close
        if "{" in report and "}" in report:
            score += 10
        
    return score


def main():
    parser = argparse.ArgumentParser(description="PyScreen LLM Benchmarking Tool v4")
    parser.add_argument("--input", default="ARES_screenshots", help="Input dataset directory")
    parser.add_argument("--levels", nargs="+", help="Specific levels to test (e.g., level_8)")
    parser.add_argument("--temperatures", type=float, nargs="+", default=[0.0, 0.3, 0.7],
                        help="Temperatures to sweep")
    parser.add_argument("--top_p", type=float, default=0.95, help="Top_p for inference")
    parser.add_argument("--top_k", type=int, default=64, help="Top_k for inference")
    args = parser.parse_args()

    results_dir = "benchmark_results"
    os.makedirs(results_dir, exist_ok=True)
    cache_path = os.path.join(results_dir, "ocr_cache.json")

    # ----------------------------------------------------------------
    # Step 1: Detect model
    # ----------------------------------------------------------------
    model_name = detect_model_name()
    print(f"[0] Detected model: {model_name}")

    model_dir = os.path.join(results_dir, model_name)
    os.makedirs(model_dir, exist_ok=True)

    # ----------------------------------------------------------------
    # Step 2: Load or Generate OCR Cache
    # ----------------------------------------------------------------
    print("[1] Checking OCR Cache...")
    cache = load_ocr_cache(cache_path)
    if cache is None:
        print("    Cache not found. Generating...")
        all_frames, state_graph = get_frames_from_ares_dir(args.input)
        if not all_frames:
            print("    Error: No frames found.")
            return
        result = text_compute(all_frames, disable_analysis=True, output_dir=results_dir)
        screen_data = result["screen_data"]
        save_ocr_cache(cache_path, screen_data, state_graph)
    else:
        print("    Cache loaded successfully.")
        screen_data = cache["screen_data"]
        state_graph = cache["state_graph"]

    if args.levels:
        screen_data = [s for s in screen_data if any(lvl in s["filename"] for lvl in args.levels)]
        if not screen_data:
            print(f"Error: No screens found for levels {args.levels}")
            return

    save_ocr_input(results_dir, screen_data, state_graph)
    levels_str = ", ".join(args.levels) if args.levels else "all"

    # ----------------------------------------------------------------
    # Step 3: Temperature sweep
    # ----------------------------------------------------------------
    all_results = []
    best_score = -1
    best_temp = None

    for temp in args.temperatures:
        config_str = f"Temp={temp}, Top_P={args.top_p}, Top_K={args.top_k}"
        report_file = os.path.join(model_dir, f"t{temp}_report.json")

        print(f"\n[2] {model_name} | {config_str}")

        start_time = time.time()
        try:
            report = analyze_screens(
                screen_data=screen_data,
                state_graph=state_graph,
                temperature=temp,
                top_p=args.top_p,
                top_k=args.top_k
            )
            success = True
        except Exception as e:
            print(f"    Inference Error: {e}")
            report = ""
            success = False

        duration = time.time() - start_time

        if not success:
            print("    FAILED.")
            all_results.append({
                "temperature": temp, "success": False,
                "time": round(duration, 2), "length": 0, "score": 0
            })
            continue

        quality_score = score_report(report)

        # Save report
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)

        result_entry = {
            "temperature": temp,
            "success": True,
            "time": round(duration, 2),
            "length": len(report),
            "score": quality_score,
        }
        all_results.append(result_entry)

        if quality_score > best_score:
            best_score = quality_score
            best_temp = temp

        print(f"    -> {duration:.1f}s | {len(report)} chars | Score: {quality_score}/100")
        print(f"       Saved: {report_file}")

    # ----------------------------------------------------------------
    # Step 4: Save metrics & best temperature
    # ----------------------------------------------------------------
    metrics = {
        "model": model_name,
        "timestamp": datetime.now().isoformat(),
        "levels": args.levels or ["all"],
        "top_p": args.top_p,
        "top_k": args.top_k,
        "temperature_sweep": all_results,
        "best_temperature": best_temp,
        "best_score": best_score,
    }
    metrics_file = os.path.join(model_dir, "metrics.json")
    with open(metrics_file, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)

    # Save best temperature indicator
    best_file = os.path.join(model_dir, "best_temperature.txt")
    with open(best_file, 'w') as f:
        f.write(f"Best Temperature: {best_temp}\n")
        f.write(f"Quality Score: {best_score}/100\n")
        f.write(f"Best Report: t{best_temp}_report.json\n")

    # ----------------------------------------------------------------
    # Step 5: Update model comparison
    # ----------------------------------------------------------------
    comparison_file = os.path.join(results_dir, "model_comparison.md")
    _update_comparison(comparison_file, model_name, all_results, best_temp, best_score)

    print(f"\n{'='*60}")
    print(f"Model: {model_name}")
    print(f"Best Temperature: {best_temp} (Score: {best_score}/100)")
    print(f"Results: {model_dir}/")
    for r in all_results:
        status = "OK" if r["success"] else "FAIL"
        print(f"  Temp={r['temperature']}: {r['time']}s | {r['length']} chars | Score={r['score']} | {status}")
    print(f"{'='*60}")


def _update_comparison(comparison_file, model_name, results, best_temp, best_score):
    """Update the cross-model comparison file."""
    entries = {}
    if os.path.exists(comparison_file):
        with open(comparison_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if (line.startswith("|") and
                    not line.startswith("| Model") and
                    not line.startswith("|---") and
                    not line.startswith("| :---")):
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) >= 6:
                        entries[parts[0]] = parts

    # Build temperature summary
    temp_summary = " / ".join(
        f"t{r['temperature']}={r['score']}pts" for r in results if r["success"]
    )
    best_result = next((r for r in results if r["temperature"] == best_temp), results[0])

    entries[model_name] = [
        model_name,
        f"{best_result['time']}s",
        str(best_result['length']),
        f"{best_temp}",
        f"{best_score}/100",
        temp_summary,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    ]

    with open(comparison_file, 'w', encoding='utf-8') as f:
        f.write("# Model Comparison — PyScreen Benchmark\n\n")
        f.write("Auto-updated each time `benchmark.py` runs. Each model is tested at multiple temperatures.\n\n")
        f.write("| Model | Best Time | Report Len | Best Temp | Score | All Temps | Tested At |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for name, row in sorted(entries.items()):
            f.write(f"| {' | '.join(row)} |\n")
        f.write("\n---\n\n")
        f.write("Full reports per model are in `benchmark_results/<model_name>/t<temp>_report.json`.\n")
        f.write("The OCR input (what all models received) is in `ocr_input.txt`.\n")


if __name__ == "__main__":
    main()
