#!/usr/bin/env python3
"""
Multi-Model 1000-State Benchmark Runner
========================================
Runs the full PyScreen pipeline (OCR + LLM) against each smaller model
sequentially. Each model gets its own results directory and performance log.
"""
import os
import cv2
import time
import json
import signal
import subprocess
import requests
import sys
from datetime import datetime

from utils.text_compute import text_compute
from utils.llm_analyze import analyze_screens

# ── Model Registry ──────────────────────────────────────────────────────────
MODELS = [
    {
        "name": "Qwen2.5-14B",
        "path": "/home/apf/Documents/models/qwen/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "params": "14B",
        "context": 16384,
    },
    {
        "name": "Phi-4-14B",
        "path": "/home/apf/Documents/models/phi/phi-4-Q4_K_M.gguf",
        "params": "14B",
        "context": 16384,
    },
    {
        "name": "Mistral-Nemo-12B",
        "path": "/home/apf/Documents/models/mistral/Mistral-Nemo-Instruct-2407-Q4_K_M.gguf",
        "params": "12B",
        "context": 16384,
    },
    {
        "name": "Gemma2-9B",
        "path": "/home/apf/Documents/models/gemma2/gemma-2-9b-it-Q4_K_M.gguf",
        "params": "9B",
        "context": 16384,
    },
    {
        "name": "LLaMA3.1-8B",
        "path": "/home/apf/Documents/models/llama/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "params": "8B",
        "context": 16384,
    },
]

API_KEY = "my_secret_token"
PORT = 8001
SERVER_URL = f"http://localhost:{PORT}"


def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}", flush=True)


def kill_existing_server():
    """Kill any running llama-server processes."""
    subprocess.run(["pkill", "-f", "llama-server"], capture_output=True)
    time.sleep(3)


def start_server(model_path, context_size, model_name):
    """Start llama-server for a given model and wait for it to be ready."""
    log_file = f"/tmp/llama_bench_{model_name}.log"
    cmd = [
        "llama-server",
        "--model", model_path,
        "-c", str(context_size),
        "--port", str(PORT),
        "--api-key", API_KEY,
    ]
    log(f"Starting llama-server for {model_name}...")
    with open(log_file, "w") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT)

    # Wait up to 120 seconds for server readiness
    for i in range(60):
        time.sleep(2)
        try:
            r = requests.get(f"{SERVER_URL}/health", timeout=5)
            if r.status_code == 200:
                log(f"Server ready for {model_name} (took {(i+1)*2}s)")
                return proc
        except requests.ConnectionError:
            pass

    log(f"ERROR: Server for {model_name} failed to start within 120s!")
    proc.kill()
    return None


def run_benchmark_for_model(model_info, all_frames, state_graph, screen_data):
    """Run the full LLM benchmark for a single model."""
    model_name = model_info["name"]
    results_dir = f"results_1000_{model_name}"
    os.makedirs(results_dir, exist_ok=True)

    log(f"{'='*60}")
    log(f"BENCHMARKING: {model_name} ({model_info['params']})")
    log(f"{'='*60}")

    # Kill any existing server & start fresh
    kill_existing_server()
    proc = start_server(model_info["path"], model_info["context"], model_name)
    if proc is None:
        return {
            "model": model_name,
            "params": model_info["params"],
            "status": "FAILED_TO_START",
            "error": "llama-server did not start within 120s",
        }

    # Tracking Variables
    llm_metrics = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "failed_calls": 0,
    }

    def my_callback(model, input_tokens, output_tokens, request_time, retries, success, error):
        llm_metrics["calls"] += 1
        if success:
            llm_metrics["input_tokens"] += input_tokens
            llm_metrics["output_tokens"] += output_tokens
        else:
            llm_metrics["failed_calls"] += 1

    start_llm = time.time()
    report = ""
    try:
        report = analyze_screens(
            screen_data=screen_data,
            state_graph=state_graph,
            temperature=0.0,
            benchmark_callback=my_callback,
        )
        llm_time = time.time() - start_llm
        log(f"{model_name}: LLM Phase Complete. Time: {llm_time:.2f}s")

        # Save output
        with open(f"{results_dir}/final_output.json", "w") as f:
            f.write(report)

    except Exception as e:
        llm_time = time.time() - start_llm
        log(f"{model_name}: LLM Phase failed after {llm_time:.2f}s: {e}")

    # Kill server after benchmark
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Build result record
    result = {
        "model": model_name,
        "params": model_info["params"],
        "status": "COMPLETE",
        "llm_time_seconds": round(llm_time, 2),
        "total_api_calls": llm_metrics["calls"],
        "input_tokens": llm_metrics["input_tokens"],
        "output_tokens": llm_metrics["output_tokens"],
        "failed_calls": llm_metrics["failed_calls"],
        "output_report_chars": len(report),
        "tokens_per_second": round(llm_metrics["output_tokens"] / llm_time, 2) if llm_time > 0 else 0,
    }

    # Save individual model metrics
    with open(f"{results_dir}/performance_metrics.json", "w") as f:
        json.dump(result, f, indent=2)

    log(f"{model_name}: Metrics saved to {results_dir}/performance_metrics.json")
    return result


def main():
    log("=" * 60)
    log("MULTI-MODEL 1000-STATE BENCHMARK")
    log(f"Models to test: {len(MODELS)}")
    log("=" * 60)

    start_total = time.time()

    # ── Phase 1: Load frames (shared across all models) ─────────────────
    log("[1] Loading 1000 frames into memory...")
    start_load = time.time()
    frames_dir = "ARES_1000_screenshots"
    image_files = sorted(
        [f for f in os.listdir(frames_dir) if f.endswith(".png")],
        key=lambda x: int(x.split("_")[1].split(".")[0]),
    )

    all_frames = []
    for i, filename in enumerate(image_files):
        level_idx = i // 20
        pseudo_filename = f"level_{level_idx}/{filename}"
        filepath = os.path.join(frames_dir, filename)
        frame = cv2.imread(filepath)
        if frame is not None:
            all_frames.append((pseudo_filename, frame))

    load_time = time.time() - start_load
    log(f"Loaded {len(all_frames)} frames in {load_time:.2f}s")

    # ── Phase 2: Parse state graph (shared) ─────────────────────────────
    log("[2] Parsing synthetic state graph...")
    state_graph = {}
    with open("ARES_1000_state_graph.txt", "r") as f:
        for line in f:
            if "->" in line:
                parts = line.strip().split("->")
                src = parts[0].replace("State ", "").strip()
                dst = parts[1].replace("State ", "").strip()
                if src not in state_graph:
                    state_graph[src] = {"transitions": []}
                state_graph[src]["transitions"].append({"to_state": dst})

    # ── Phase 3: OCR (shared, run once) ─────────────────────────────────
    log("[3] Running OCR phase (shared across all models)...")
    start_ocr = time.time()
    result = text_compute(all_frames, disable_analysis=True, output_dir="results_1000_benchmark")
    screen_data = result["screen_data"]
    ocr_time = time.time() - start_ocr
    log(f"OCR Complete: {ocr_time:.2f}s ({ocr_time/len(all_frames):.3f}s per image)")

    # ── Phase 4: Run each model sequentially ────────────────────────────
    all_results = []
    for i, model_info in enumerate(MODELS, 1):
        log(f"\n{'#'*60}")
        log(f"MODEL {i}/{len(MODELS)}: {model_info['name']}")
        log(f"{'#'*60}")

        result = run_benchmark_for_model(model_info, all_frames, state_graph, screen_data)
        all_results.append(result)

        # Save cumulative progress after each model
        with open("benchmark_all_models_results.json", "w") as f:
            json.dump({
                "ocr_time_seconds": round(ocr_time, 2),
                "total_frames": len(all_frames),
                "models": all_results,
            }, f, indent=2)

        log(f"Progress saved. {len(all_results)}/{len(MODELS)} models complete.")

        # Brief cooldown between models
        if i < len(MODELS):
            log("Cooling down for 10 seconds before next model...")
            time.sleep(10)

    total_time = time.time() - start_total

    # ── Final Summary ───────────────────────────────────────────────────
    log("\n" + "=" * 60)
    log("       MULTI-MODEL BENCHMARK COMPLETE")
    log("=" * 60)
    log(f"Total Wall Time: {total_time:.2f}s ({total_time/3600:.1f} hours)")
    log(f"OCR Time (shared): {ocr_time:.2f}s")
    log("-" * 60)
    log(f"{'Model':<22} {'Params':<8} {'LLM Time':<12} {'Tok/s':<8} {'Failed':<8}")
    log("-" * 60)
    for r in all_results:
        if r["status"] == "COMPLETE":
            log(
                f"{r['model']:<22} {r['params']:<8} {r['llm_time_seconds']:<12.1f} "
                f"{r['tokens_per_second']:<8.1f} {r['failed_calls']:<8}"
            )
        else:
            log(f"{r['model']:<22} {r['params']:<8} {'FAILED':<12} {'N/A':<8} {'N/A':<8}")
    log("=" * 60)
    log("All results saved to benchmark_all_models_results.json")


if __name__ == "__main__":
    main()
