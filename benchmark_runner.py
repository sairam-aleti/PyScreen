#!/usr/bin/env python3
"""
PyScreen Benchmark Runner

Automatically runs both the screenshot and video approaches on all available
example datasets and generates a comparison report.

Usage:
    python benchmark_runner.py
    python benchmark_runner.py --datasets duolingo sensibo
    python benchmark_runner.py --disable_analysis   # OCR-only benchmark (no API key needed)
"""
import argparse
import os
import sys
import json
import logging
from datetime import datetime

from utils.clean_folders import clean_folders
from utils.frames import get_frames_from_dir, get_frames_from_video
from utils.text_compute import text_compute
from utils.benchmark import BenchmarkTracker
from utils.report_generator import generate_comparison_report


# Known example datasets and their paths
EXAMPLE_DATASETS = {
    "duolingo": {
        "screenshots": "examples/duolingo/result",
        "video": "examples/duolingo/duolingo.mov",
    },
    "sensibo": {
        "screenshots": "examples/sensibo/result",
        "video": "examples/sensibo/sensibo.mov",
    },
    "settings": {
        "screenshots": "examples/settings/result",
        "video": "examples/settings/settings.mov",
    },
    "translate": {
        "screenshots": "examples/translate/result",
        "video": "examples/translate/translate.mov",
    },
}


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    # Force UTF-8 encoding on Windows to avoid cp1252 errors
    if hasattr(handler.stream, 'reconfigure'):
        handler.stream.reconfigure(encoding='utf-8', errors='replace')
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    return logging.getLogger("pyscreen")


def run_single_benchmark(mode, dataset_name, input_path, output_dir, disable_analysis=False):
    """
    Run a single benchmark for one mode + dataset combination.

    Returns:
        BenchmarkResult as a dict, or None if the input doesn't exist.
    """
    logger = logging.getLogger("pyscreen")

    # Check input exists
    if mode == "screenshots" and not os.path.isdir(input_path):
        logger.warning(f"  Skipping {mode}/{dataset_name}: directory not found ({input_path})")
        return None
    if mode == "video" and not os.path.isfile(input_path):
        logger.warning(f"  Skipping {mode}/{dataset_name}: video not found ({input_path})")
        return None

    # Setup tracker
    tracker = BenchmarkTracker(mode=mode, dataset=dataset_name, input_path=input_path)
    tracker.start()

    try:
        # Prepare output dir
        clean_folders(output_dir)

        # Load frames
        with tracker.phase("frame_loading"):
            if mode == "screenshots":
                all_frames = get_frames_from_dir(input_path)
            else:
                all_frames = get_frames_from_video(input_path, sample_rate=1.0)

        tracker.set_num_frames(len(all_frames))

        if len(all_frames) == 0:
            logger.warning(f"  No frames loaded for {mode}/{dataset_name}")
            return None

        # Run OCR + analysis
        result = text_compute(
            all_frames,
            disable_analysis=disable_analysis,
            output_dir=output_dir,
            tracker=tracker,
        )

        bench_result = tracker.finish()
        return bench_result.to_dict()

    except Exception as e:
        logger.error(f"  Error in {mode}/{dataset_name}: {e}")
        try:
            bench_result = tracker.finish()
            bench_result.success = False
            bench_result.error = str(e)
            return bench_result.to_dict()
        except Exception:
            return {
                "mode": mode,
                "dataset": dataset_name,
                "input_path": input_path,
                "success": False,
                "error": str(e),
            }


def main():
    parser = argparse.ArgumentParser(description="PyScreen Benchmark Runner")
    parser.add_argument('--datasets', nargs='+', default=None,
                        help='Specific datasets to benchmark. Default: all available.')
    parser.add_argument('--modes', nargs='+', default=['screenshots', 'video'],
                        choices=['screenshots', 'video'],
                        help='Modes to benchmark. Default: both.')
    parser.add_argument('--disable_analysis', action='store_true',
                        help='Skip Gemini analysis (OCR-only benchmark, no API key needed).')
    parser.add_argument('--output_dir', type=str, default='result',
                        help='Base output directory. Default: result/')

    args = parser.parse_args()
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("  PyScreen Benchmark Runner")
    logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Determine which datasets to run
    datasets_to_run = args.datasets or list(EXAMPLE_DATASETS.keys())

    logger.info(f"\n  Datasets: {', '.join(datasets_to_run)}")
    logger.info(f"  Modes:    {', '.join(args.modes)}")
    logger.info(f"  Analysis: {'disabled (OCR only)' if args.disable_analysis else 'enabled (Gemini AI)'}")
    logger.info("")

    all_results = []
    total_runs = len(datasets_to_run) * len(args.modes)
    current_run = 0

    for dataset_name in datasets_to_run:
        if dataset_name not in EXAMPLE_DATASETS:
            logger.warning(f"Unknown dataset: {dataset_name}. Skipping.")
            continue

        dataset_info = EXAMPLE_DATASETS[dataset_name]

        for mode in args.modes:
            current_run += 1
            input_path = dataset_info.get(mode, "")

            logger.info(f"\n{'-' * 60}")
            logger.info(f"  [{current_run}/{total_runs}] {dataset_name.upper()} - {mode}")
            logger.info(f"  Input: {input_path}")
            logger.info(f"{'-' * 60}")

            # Use separate output dirs to avoid conflicts
            run_output_dir = os.path.join(args.output_dir, f"bench_{dataset_name}_{mode}")

            result = run_single_benchmark(
                mode=mode,
                dataset_name=dataset_name,
                input_path=input_path,
                output_dir=run_output_dir,
                disable_analysis=args.disable_analysis,
            )

            if result:
                all_results.append(result)
                status = "[OK] SUCCESS" if result.get("success", False) else "[X] FAILED"
                time_str = f"{result.get('total_time_seconds', 0):.2f}s"
                logger.info(f"\n  Result: {status} | Time: {time_str}")
            else:
                logger.info(f"\n  Result: SKIPPED (input not found)")

    # Generate comparison report
    if len(all_results) > 0:
        logger.info(f"\n{'=' * 60}")
        logger.info("  Generating comparison report...")
        logger.info(f"{'=' * 60}\n")

        report = generate_comparison_report(all_results, args.output_dir)
        logger.info(report)

        logger.info(f"\n  Report saved to: {args.output_dir}/benchmark_report.txt")
        logger.info(f"  Raw metrics:     {args.output_dir}/benchmark_metrics.json")
    else:
        logger.warning("\n  No benchmarks completed. Nothing to report.")


if __name__ == "__main__":
    main()
