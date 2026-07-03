"""
Benchmarking infrastructure for PyScreen.
Tracks timing, memory, token usage, and cost metrics.
"""
import time
import tracemalloc
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Optional


# Gemini pricing (per 1M tokens) — as of June 2026
# https://ai.google.dev/pricing
PRICING = {
    "gemini-3.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-3.1-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # Fallback for unknown models
    "default": {"input": 0.15, "output": 0.60},
}


@dataclass
class PhaseMetrics:
    """Metrics for a single phase of the pipeline."""
    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float = 0.0
    success: bool = True
    error: Optional[str] = None

    def to_dict(self):
        return {
            "name": self.name,
            "duration_seconds": round(self.duration_seconds, 3),
            "success": self.success,
            "error": self.error,
        }


@dataclass
class APIMetrics:
    """Metrics specific to the Gemini API call."""
    model: str = ""
    request_time_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    success: bool = True
    error: Optional[str] = None
    retries: int = 0

    def to_dict(self):
        return {
            "model": self.model,
            "request_time_seconds": round(self.request_time_seconds, 3),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "success": self.success,
            "error": self.error,
            "retries": self.retries,
        }


@dataclass
class BenchmarkResult:
    """Complete benchmark result for a single run."""
    mode: str  # "screenshots" or "video"
    dataset: str  # e.g., "duolingo"
    input_path: str
    num_frames: int = 0
    total_time_seconds: float = 0.0
    peak_memory_mb: float = 0.0
    phases: list = field(default_factory=list)
    api_metrics: APIMetrics = field(default_factory=APIMetrics)
    success: bool = True
    error: Optional[str] = None
    analysis_output_length: int = 0

    def to_dict(self):
        return {
            "mode": self.mode,
            "dataset": self.dataset,
            "input_path": self.input_path,
            "num_frames": self.num_frames,
            "total_time_seconds": round(self.total_time_seconds, 3),
            "peak_memory_mb": round(self.peak_memory_mb, 2),
            "phases": [p.to_dict() if hasattr(p, 'to_dict') else p for p in self.phases],
            "api_metrics": self.api_metrics.to_dict(),
            "success": self.success,
            "error": self.error,
            "analysis_output_length": self.analysis_output_length,
        }


class BenchmarkTracker:
    """
    Tracks benchmark metrics throughout a pipeline run.

    Usage:
        tracker = BenchmarkTracker(mode="screenshots", dataset="duolingo", input_path="...")
        tracker.start()

        with tracker.phase("frame_loading"):
            # load frames...
            pass

        with tracker.phase("ocr_processing"):
            # run OCR...
            pass

        tracker.record_api_metrics(model, input_tokens, output_tokens, request_time)
        result = tracker.finish()
    """

    def __init__(self, mode: str, dataset: str, input_path: str):
        self.result = BenchmarkResult(
            mode=mode,
            dataset=dataset,
            input_path=input_path,
        )
        self._start_time = None
        self._memory_tracking = False

    def start(self):
        """Start the benchmark timer and memory tracking."""
        self._start_time = time.perf_counter()
        try:
            tracemalloc.start()
            self._memory_tracking = True
        except Exception:
            self._memory_tracking = False

    @contextmanager
    def phase(self, name: str):
        """Context manager to time a phase of the pipeline."""
        metrics = PhaseMetrics(name=name)
        metrics.start_time = time.perf_counter()
        try:
            yield metrics
            metrics.success = True
        except Exception as e:
            metrics.success = False
            metrics.error = str(e)
            raise
        finally:
            metrics.end_time = time.perf_counter()
            metrics.duration_seconds = metrics.end_time - metrics.start_time
            self.result.phases.append(metrics)

    def record_api_metrics(self, model: str, input_tokens: int, output_tokens: int,
                           request_time: float, retries: int = 0,
                           success: bool = True, error: str = None):
        """Record API-specific metrics."""
        self.result.api_metrics = APIMetrics(
            model=model,
            request_time_seconds=request_time,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated_cost_usd=self._calculate_cost(model, input_tokens, output_tokens),
            success=success,
            error=error,
            retries=retries,
        )

    def set_num_frames(self, count: int):
        """Record number of frames processed."""
        self.result.num_frames = count

    def set_analysis_length(self, length: int):
        """Record length of analysis output."""
        self.result.analysis_output_length = length

    def finish(self) -> BenchmarkResult:
        """Stop tracking and return the final result."""
        if self._start_time:
            self.result.total_time_seconds = time.perf_counter() - self._start_time

        if self._memory_tracking:
            try:
                _, peak = tracemalloc.get_traced_memory()
                self.result.peak_memory_mb = peak / (1024 * 1024)
                tracemalloc.stop()
            except Exception:
                pass

        return self.result

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate estimated cost based on model pricing."""
        pricing = PRICING.get(model, PRICING["default"])
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def save_to_json(self, filepath: str):
        """Save benchmark result to a JSON file."""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.result.to_dict(), f, indent=2)
