"""
Text extraction and analysis pipeline for PyScreen.
Runs OCR on screenshots and sends results to Gemini for analysis.
"""
import os
import cv2
import time
import logging
import pytesseract

# Set Tesseract path for Windows
if os.name == 'nt':
    tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

from utils.llm_analyze import analyze_screens

logger = logging.getLogger("pyscreen")


def text_compute(frames, disable_analysis, output_dir="result", tracker=None, state_graph=None):
    """
    For each screenshot:
      1. Extract all visible text via OCR.
      2. Bundle it with the filename.
    Then send the full bundle to Gemini for a detailed user-journey analysis.

    Args:
        frames: List of (filename, frame) tuples.
        disable_analysis: If True, skip Gemini analysis.
        output_dir: Directory to save output files. Default: "result"
        tracker: Optional BenchmarkTracker for metrics collection.
        state_graph: Optional dictionary representing the state transition graph.


    Returns:
        dict with 'screen_data', 'analysis_report' (or None), and 'success' status.
    """
    os.makedirs(output_dir, exist_ok=True)

    result = {
        "screen_data": [],
        "analysis_report": None,
        "success": True,
        "error": None,
    }

    # Phase: OCR Processing
    screen_data = []
    ocr_phase_name = "ocr_processing"

    if tracker:
        ctx = tracker.phase(ocr_phase_name)
    else:
        from contextlib import nullcontext
        ctx = nullcontext()

    with ctx:
        for index, (filename, img) in enumerate(frames):
            logger.info(f"  Scanning ({index+1}/{len(frames)}): {filename}")
            try:
                text = image_to_string(img)
            except Exception as e:
                logger.warning(f"  OCR failed for {filename}: {e}")
                text = f"[OCR ERROR: {e}]"

            screen_data.append({
                "screen_number": index + 1,
                "filename": filename,
                "extracted_text": text.strip()
            })

    result["screen_data"] = screen_data

    # Save raw extracted text
    text_path = os.path.join(output_dir, "extracted_text.txt")
    with open(text_path, "w", encoding="utf-8") as f:
        for screen in screen_data:
            f.write(f"--- Screen {screen['screen_number']}: {screen['filename']} ---\n")
            f.write(screen["extracted_text"])
            f.write("\n\n")
    logger.info(f"  Raw text saved to {text_path}")

    # Phase: Gemini Analysis
    if not disable_analysis:
        logger.info("  Running Gemini analysis (this may take a moment)...")

        # Benchmark callback to capture API metrics
        def api_callback(model, input_tokens, output_tokens, request_time,
                         retries, success, error):
            if tracker:
                tracker.record_api_metrics(
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    request_time=request_time,
                    retries=retries,
                    success=success,
                    error=error,
                )

        gemini_phase_name = "gemini_analysis"
        if tracker:
            ctx = tracker.phase(gemini_phase_name)
        else:
            from contextlib import nullcontext
            ctx = nullcontext()

        with ctx:
            try:
                analysis_report = analyze_screens(
                    screen_data,
                    benchmark_callback=api_callback,
                    state_graph=state_graph,
                )
                result["analysis_report"] = analysis_report

                # Save analysis report
                report_path = os.path.join(output_dir, "analysis_report.txt")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(analysis_report)
                logger.info(f"  Analysis report saved to {report_path}")

                if tracker:
                    tracker.set_analysis_length(len(analysis_report))

            except Exception as e:
                error_msg = str(e)
                logger.error(f"  Gemini analysis failed: {error_msg}")
                result["success"] = False
                result["error"] = error_msg

                # Save error to report file
                report_path = os.path.join(output_dir, "analysis_report.txt")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(f"Analysis failed: {error_msg}\n")
    else:
        logger.info("  Gemini analysis skipped (--disable_analysis flag).")

    return result


def image_to_string(img):
    """
    Convert an image to text using Tesseract OCR.

    Args:
        img: OpenCV image (BGR format).

    Returns:
        Extracted text string.

    Raises:
        RuntimeError: If Tesseract is not installed or accessible.
    """
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 3)
        text = pytesseract.image_to_string(gray, lang="eng")
        return text
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract OCR is not installed or not in PATH.\n"
            "Install it:\n"
            "  Windows: winget install tesseract-ocr.tesseract\n"
            "  macOS:   brew install tesseract\n"
            "  Linux:   sudo apt install tesseract-ocr\n"
        )
