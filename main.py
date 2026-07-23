#!/usr/bin/env python3
"""
PyScreen - Android Side-Channel Screen Analyzer

Analyzes screenshots or video recordings from Android apps using OCR and local LLMs
to extract context, identify user actions, and flag security/privacy concerns.

Usage:
    # Analyze a folder of numbered screenshots
    python main.py --input examples/duolingo/result --mode screenshots

    # Analyze a video recording
    python main.py --video examples/duolingo/duolingo.mov --mode video

    # With benchmarking enabled
    python main.py --input examples/duolingo/result --mode screenshots --benchmark

    # OCR only (no AI analysis)
    python main.py --input examples/duolingo/result --disable_analysis
"""
import argparse
import os
import sys
import logging
from pathlib import Path

from utils.clean_folders import clean_folders
from utils.frames import get_frames_from_dir, get_frames_from_video, get_frames_from_ares_dir
from utils.text_compute import text_compute
from utils.benchmark import BenchmarkTracker


def setup_logging(verbose=False):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    if hasattr(handler.stream, 'reconfigure'):
        handler.stream.reconfigure(encoding='utf-8', errors='replace')
    logging.basicConfig(level=level, handlers=[handler])
    return logging.getLogger("pyscreen")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='PyScreen - Android Side-Channel Screen Analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --input examples/duolingo/result --mode screenshots
  python main.py --video examples/duolingo/duolingo.mov --mode video
  python main.py --input examples/duolingo/result --benchmark
  python main.py --input examples/duolingo/result --disable_analysis
        """
    )

    parser.add_argument('--mode', type=str, choices=['screenshots', 'video', 'ares'],
                        default='screenshots',
                        help='Analysis mode: "screenshots" (folder of images), "video" (video file), or "ares" (nested state graph folders). Default: screenshots')
    parser.add_argument('--input', type=str,
                        help='Path to directory containing screenshots (for screenshots/ares modes).')
    parser.add_argument('--video', type=str,
                        help='Path to video file (for video mode).')
    parser.add_argument('--sample_rate', type=float, default=1.0,
                        help='Frames to extract per second from video. Default: 1.0')
    parser.add_argument('--output_dir', type=str, default='result',
                        help='Output directory for results. Default: result/')
    parser.add_argument('--disable_analysis', action='store_true',
                        help='Disable LLM analysis (only extract text via OCR).')
    parser.add_argument('--benchmark', action='store_true',
                        help='Enable benchmarking — track timing, memory, and API metrics.')
    parser.add_argument('--model', type=str, default=None,
                        help='Local LLM model to use. Default: value from LLAMA_CPP_MODEL env var')
    parser.add_argument('--verbose', action='store_true',
                        help='Enable verbose debug logging.')

    args = parser.parse_args()

    # Validate mode-specific arguments
    if args.mode in ['screenshots', 'ares']:
        if not args.input:
            parser.error(f"--input is required when --mode is '{args.mode}'")
        input_path = Path(args.input)
        if not input_path.exists():
            parser.error(f"The path '{args.input}' does not exist.")
        if not input_path.is_dir():
            parser.error(f"'{args.input}' is not a directory.")

    elif args.mode == 'video':
        if not args.video:
            parser.error("--video is required when --mode is 'video'")
        video_path = Path(args.video)
        if not video_path.exists():
            parser.error(f"The video file '{args.video}' does not exist.")
        if not video_path.is_file():
            parser.error(f"'{args.video}' is not a file.")

    return args


########
# Main #
########
if __name__ == "__main__":
    args = parse_arguments()
    logger = setup_logging(args.verbose)

    logger.info("=== PyScreen - Screen Analyzer ===")
    logger.info(f"Mode: {args.mode}")
    logger.info("")

    # Setup benchmark tracker if enabled
    tracker = None
    if args.benchmark:
        dataset_name = ""
        input_path = ""
        if args.mode in ['screenshots', 'ares']:
            dataset_name = os.path.basename(os.path.dirname(args.input)) or os.path.basename(args.input)
            input_path = args.input
        else:
            dataset_name = os.path.splitext(os.path.basename(args.video))[0]
            input_path = args.video

        tracker = BenchmarkTracker(
            mode=args.mode,
            dataset=dataset_name,
            input_path=input_path,
        )
        tracker.start()
        logger.info("[BENCHMARK] Tracking enabled.")

    try:
        # Step 1: Clean output folder
        logger.info("[1/3] Preparing result folder...")
        clean_folders(args.output_dir)

        # Step 2: Load frames
        state_graph = None
        if args.mode == 'screenshots':
            logger.info(f"[2/3] Loading screenshots from: {args.input}")

            if tracker:
                with tracker.phase("frame_loading"):
                    all_frames = get_frames_from_dir(args.input)
            else:
                all_frames = get_frames_from_dir(args.input)

        elif args.mode == 'ares':
            logger.info(f"[2/3] Loading ARES state graph from: {args.input}")

            if tracker:
                with tracker.phase("frame_loading"):
                    all_frames, state_graph = get_frames_from_ares_dir(args.input)
            else:
                all_frames, state_graph = get_frames_from_ares_dir(args.input)

        elif args.mode == 'video':
            logger.info(f"[2/3] Extracting frames from video: {args.video}")

            if tracker:
                with tracker.phase("frame_loading"):
                    all_frames = get_frames_from_video(args.video, args.sample_rate)
            else:
                all_frames = get_frames_from_video(args.video, args.sample_rate)

        if len(all_frames) == 0:
            logger.error("No frames found. Exiting.")
            sys.exit(1)

        if tracker:
            tracker.set_num_frames(len(all_frames))

        # Step 3: Extract text and analyze
        logger.info(f"[3/3] Extracting text and running analysis...")
        result = text_compute(
            all_frames,
            args.disable_analysis,
            output_dir=args.output_dir,
            tracker=tracker,
            state_graph=state_graph,
        )

        if result["success"]:
            logger.info("")
            logger.info(f"Done! Check the '{args.output_dir}/' folder for results.")
        else:
            logger.error(f"\nAnalysis completed with errors: {result['error']}")
            logger.info(f"OCR text was still saved to '{args.output_dir}/extracted_text.txt'")

    except FileNotFoundError as e:
        logger.error(f"\nFile not found: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"\nConfiguration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\nUnexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        # Save benchmark results
        if tracker:
            bench_result = tracker.finish()
            bench_json_path = os.path.join(args.output_dir, "benchmark_metrics.json")
            tracker.save_to_json(bench_json_path)
            logger.info(f"\n[BENCHMARK] Results saved to {bench_json_path}")
            logger.info(f"  Total time:   {bench_result.total_time_seconds:.2f}s")
            logger.info(f"  Peak memory:  {bench_result.peak_memory_mb:.1f} MB")
            logger.info(f"  Frames:       {bench_result.num_frames}")
            if bench_result.api_metrics.total_tokens > 0:
                logger.info(f"  Tokens:       {bench_result.api_metrics.total_tokens} "
                           f"(in: {bench_result.api_metrics.input_tokens}, "
                           f"out: {bench_result.api_metrics.output_tokens})")
                logger.info(f"  Est. cost:    ${bench_result.api_metrics.estimated_cost_usd:.6f}")