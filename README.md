# PyScreen

PyScreen is a local pipeline that analyzes Android application screenshots and automatically generates a structured JSON report mapping the application's user journey and UI states.

## Architecture (V4)

PyScreen operates entirely locally with zero cloud dependencies:

1. **Text Extraction (OCR):** Uses Tesseract OCR. Screenshots are pre-processed via OpenCV (200% upscaling and adaptive thresholding) to accurately capture small mobile UI elements like buttons.
2. **Deterministic Verification:** Employs a Python-native deterministic verifier to cross-check LLM outputs against raw OCR data, preventing hallucinations.
3. **Local LLM Inference:** Connects to OpenAI-compatible local endpoints (e.g., `llama.cpp` server) to run 8B-32B class models on local GPU hardware.
4. **Visual Mapping:** Automatically parses the output JSON and generates a Mermaid.js flowchart mapping the application's workflows.

## Prerequisites

- Python 3.9+
- Tesseract OCR installed on your system (`sudo apt install tesseract-ocr`)
- `llama-server` (from the `llama.cpp` project) or Ollama running locally.
- NVIDIA GPU with enough VRAM to host your chosen quantized model (e.g., 24GB for a 32B model at Q4_K_M).

## Installation

```bash
git clone https://github.com/alexandrevl/pyscreen.git
cd pyscreen
python -m venv pyscreen_env
source pyscreen_env/bin/activate
pip install -r requirements.txt
```

*(Note: If `requirements.txt` is missing, manually install: `opencv-python pytesseract`)*

## Configuration

Set your environment variables in a `.env` file or export them directly:

```bash
LLM_BACKEND="llama_cpp"                 # or "ollama"
LLAMA_CPP_HOST="http://localhost:8001"
LLAMA_CPP_API_KEY="my_secret_token"     # Only if configured in llama-server
LLAMA_CPP_MODEL="Qwen2.5-32B-Instruct-Q4_K_M"
```

## Usage

Start your local LLM server:
```bash
llama-server --model /path/to/model.gguf -c 16384 --port 8001
```

Run PyScreen on a directory containing application screenshots (e.g., ARES output):
```bash
python main.py --mode ares --input ./ARES_screenshots --output_dir ./results
```

To run a temperature sweep benchmark across multiple settings:
```bash
python benchmark.py --input ./ARES_screenshots --temperatures 0.0 0.3 0.7 --output-dir ./benchmark_results
```

## Outputs

PyScreen generates the following in your output directory:
- `t0.0_report.json`: The raw, structured JSON report containing `app_summary`, `core_workflows`, and detailed `screen_contexts`.
- `workflow_map.md`: An automatically generated Mermaid flowchart mapping the user journeys.
- `ocr_cache.json`: Cached OCR text to speed up subsequent runs.

## License

MIT License
