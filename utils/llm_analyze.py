"""
LLM analysis module for PyScreen.
Supports three backends:
  - "gemini"    : Google Gemini cloud API (requires GEMINI_API_KEY)
  - "ollama"    : Local Ollama server (requires Ollama running)
  - "llama_cpp" : Local llama.cpp server (llama-server, OpenAI-compatible API)

Set the LLM_BACKEND env var to choose. Default is "gemini".
"""
import os
import time
import logging
import json
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("pyscreen")

# Default models per backend
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_OLLAMA_MODEL = "gemma3:27b"
DEFAULT_LLAMA_CPP_MODEL = "Gemma 4 31B QAT"  # alias set in llama-server

# Backend selection
LLM_BACKEND = os.getenv("LLM_BACKEND", "gemini").strip().lower()

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAYS = [30, 60, 120]  # seconds between retries
REQUEST_TIMEOUT = 120  # seconds

# Local server hosts
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
LLAMA_CPP_HOST = os.getenv("LLAMA_CPP_HOST", "http://localhost:8001").strip()
LLAMA_CPP_API_KEY = os.getenv("LLAMA_CPP_API_KEY", "my_secret_token").strip()


def validate_api_key():
    """
    Check that a Gemini API key is configured.

    Returns:
        The API key string.

    Raises:
        ValueError: If the key is missing or empty.
    """
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "GEMINI_API_KEY not found in environment.\n"
            "To fix this:\n"
            "  1. Go to https://aistudio.google.com/apikey\n"
            "  2. Sign in with your Google account\n"
            "  3. Click 'Create API Key'\n"
            "  4. Copy the key\n"
            "  5. Add it to your .env file: GEMINI_API_KEY=your_key_here\n"
        )
    return key


def analyze_screens(screen_data, model=None, benchmark_callback=None, state_graph=None, **kwargs):
    """
    Send extracted screen text data to an LLM for a detailed
    user-journey and security analysis report.

    Supports two backends (set via LLM_BACKEND env var):
      - "gemini": Google Gemini cloud API
      - "ollama": Local Ollama server (e.g., Gemma, Llama)

    Args:
        screen_data: List of dicts with 'screen_number', 'filename', 'extracted_text'
        model: Model name to use. Defaults to env var or built-in default.
        benchmark_callback: Optional callable(model, input_tokens, output_tokens, request_time,
                            retries, success, error) for metrics collection.
        state_graph: Optional dict representing the app's state transition graph.

    Returns:
        The analysis report as a string.

    Raises:
        ValueError: If API key is not configured (Gemini backend only).
        RuntimeError: If all retries are exhausted.
    """
    backend = LLM_BACKEND
    logger.info(f"Using LLM backend: {backend}")

    if backend == "gemini":
        from google import genai
        api_key = validate_api_key()
        model_name = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    elif backend == "ollama":
        import requests as _requests
        model_name = model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        logger.info(f"Ollama model: {model_name} at {OLLAMA_HOST}")
    elif backend == "llama_cpp":
        import requests as _requests
        model_name = model or os.getenv("LLAMA_CPP_MODEL", DEFAULT_LLAMA_CPP_MODEL)
        logger.info(f"llama.cpp model: {model_name} at {LLAMA_CPP_HOST}")
    else:
        raise ValueError(f"Unknown LLM_BACKEND: '{backend}'. Use 'gemini', 'ollama', or 'llama_cpp'.")

    def _call_ollama(prompt):
        """Call the local Ollama REST API."""
        import requests as _requests
        url = f"{OLLAMA_HOST}/api/generate"
        start_time = time.perf_counter()

        try:
            resp = _requests.post(url, json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
            }, timeout=600)  # 10 min timeout for large models on CPU
            resp.raise_for_status()
        except _requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {OLLAMA_HOST}. "
                "Make sure Ollama is running: 'ollama serve'"
            )
        except _requests.exceptions.Timeout:
            raise RuntimeError(
                f"Ollama request timed out after 600s. The model may be too large for CPU inference."
            )

        request_time = time.perf_counter() - start_time
        data = resp.json()
        text = data.get("response", "")

        # Extract token counts from Ollama response
        input_tokens = data.get("prompt_eval_count", 0) or 0
        output_tokens = data.get("eval_count", 0) or 0

        logger.info(f"Ollama response received in {request_time:.1f}s")
        logger.info(f"Tokens — input: {input_tokens}, output: {output_tokens}")

        if benchmark_callback:
            benchmark_callback(
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_time=request_time,
                retries=0,
                success=True,
                error=None,
            )

        return text

    def _call_llama_cpp(prompt):
        """Call the local llama.cpp server (OpenAI-compatible API)."""
        import requests as _requests
        url = f"{LLAMA_CPP_HOST}/v1/chat/completions"
        start_time = time.perf_counter()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLAMA_CPP_API_KEY}",
        }

        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": kwargs.get("temperature", 1.0),
            "top_p": kwargs.get("top_p", 0.95),
            "top_k": kwargs.get("top_k", 64),
            "response_format": {"type": "json_object"},
            "stream": False,
        }

        try:
            resp = _requests.post(url, json=payload, headers=headers, timeout=600)
            resp.raise_for_status()
        except _requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to llama-server at {LLAMA_CPP_HOST}. "
                "Make sure llama-server is running. Start it with:\n"
                "  llama-server --model ./gemma-4-31B-it-qat-UD-Q4_K_XL.gguf "
                "--port 8001 --api-key your_token"
            )
        except _requests.exceptions.Timeout:
            raise RuntimeError(
                "llama-server request timed out after 600s. "
                "The model may be too large for your hardware."
            )
        except _requests.exceptions.HTTPError as e:
            if resp.status_code == 401:
                raise RuntimeError(
                    "llama-server returned 401 Unauthorized. "
                    "Check that LLAMA_CPP_API_KEY in .env matches the --api-key used to start llama-server."
                )
            raise RuntimeError(f"llama-server HTTP error: {e}")

        request_time = time.perf_counter() - start_time
        data = resp.json()

        # Extract response text from OpenAI-compatible format
        text = ""
        if "choices" in data and len(data["choices"]) > 0:
            text = data["choices"][0].get("message", {}).get("content", "")

        # Extract token counts
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0) or 0
        output_tokens = usage.get("completion_tokens", 0) or 0

        logger.info(f"llama.cpp response received in {request_time:.1f}s")
        logger.info(f"Tokens — input: {input_tokens}, output: {output_tokens}")

        if benchmark_callback:
            benchmark_callback(
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_time=request_time,
                retries=0,
                success=True,
                error=None,
            )

        return text

    def _call_api(prompt):
        logger.info(f"Calling LLM ({backend}: {model_name})...")
        logger.debug(f"Prompt length: {len(prompt)} characters")

        if backend == "ollama":
            return _call_ollama(prompt)
        if backend == "llama_cpp":
            return _call_llama_cpp(prompt)

        # --- Gemini backend ---
        last_error = None
        retries_used = 0

        for attempt in range(MAX_RETRIES + 1):
            try:
                client = genai.Client(api_key=api_key)
                start_time = time.perf_counter()

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )

                request_time = time.perf_counter() - start_time

                # Extract token usage if available
                input_tokens = 0
                output_tokens = 0
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
                    output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

                logger.info(f"API response received in {request_time:.1f}s")
                logger.info(f"Tokens — input: {input_tokens}, output: {output_tokens}")

                # Report metrics
                if benchmark_callback:
                    benchmark_callback(
                        model=model_name,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        request_time=request_time,
                        retries=retries_used,
                        success=True,
                        error=None,
                    )

                return response.text

            except Exception as e:
                last_error = e
                error_str = str(e)

                # Check for rate limit (429)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    if attempt < MAX_RETRIES:
                        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                        retries_used += 1
                        logger.warning(
                            f"Rate limited (429). Retry {retries_used}/{MAX_RETRIES} "
                            f"in {delay}s..."
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.error("Rate limit: all retries exhausted.")

                # Check for invalid API key
                elif "401" in error_str or "UNAUTHENTICATED" in error_str:
                    logger.error(
                        "Invalid API key. Please check your GEMINI_API_KEY in .env file.\n"
                        "Get a new key at: https://aistudio.google.com/apikey"
                    )
                    if benchmark_callback:
                        benchmark_callback(
                            model=model_name, input_tokens=0, output_tokens=0,
                            request_time=0, retries=retries_used,
                            success=False, error=f"Invalid API key: {error_str}",
                        )
                    raise ValueError(f"Invalid Gemini API key: {error_str}")

                # Check for server error (500+)
                elif "500" in error_str or "503" in error_str or "INTERNAL" in error_str:
                    if attempt < MAX_RETRIES:
                        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                        retries_used += 1
                        logger.warning(f"Server error. Retry {retries_used}/{MAX_RETRIES} in {delay}s...")
                        time.sleep(delay)
                        continue

                # Unknown error — don't retry
                else:
                    logger.error(f"Gemini API error: {error_str}")
                    if benchmark_callback:
                        benchmark_callback(
                            model=model_name, input_tokens=0, output_tokens=0,
                            request_time=0, retries=retries_used,
                            success=False, error=error_str,
                        )
                    raise RuntimeError(f"Gemini API error: {error_str}")

        # All retries exhausted
        if benchmark_callback:
            benchmark_callback(
                model=model_name, input_tokens=0, output_tokens=0,
                request_time=0, retries=retries_used,
                success=False, error=str(last_error),
            )
        raise RuntimeError(
            f"Gemini API failed after {MAX_RETRIES} retries. Last error: {last_error}"
        )

    if not state_graph:
        prompt = _build_prompt(screen_data)
        return _call_api(prompt)

    # ARES mode: Process sequentially by level to avoid 503 Server Error for massive prompts
    logger.info("Grouping screens by level for sequential batch analysis...")
    from collections import defaultdict
    import time
    levels = defaultdict(list)
    for screen in screen_data:
        # Assuming filename is something like 'level_8/state_0.png'
        if '/' in screen['filename'] or '\\' in screen['filename']:
            # Handle both forward and backslashes
            level_name = screen['filename'].replace('\\', '/').split('/')[0]
        else:
            level_name = 'unknown_level'
        levels[level_name].append(screen)

    all_screen_contexts = []
    logger.info(f"Processing {len(levels)} levels sequentially to avoid server timeouts...")
    for i, (level_name, level_screens) in enumerate(levels.items(), 1):
        logger.info(f"  Analyzing level {i}/{len(levels)}: {level_name} ({len(level_screens)} screens)...")
        prompt = _build_ares_batch_prompt(level_screens, state_graph, level_name)
        try:
            report = _call_api(prompt)
            import json
            try:
                data = json.loads(report)
                if "screen_contexts" in data:
                    all_screen_contexts.extend(data["screen_contexts"])
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON for {level_name}: {report[:100]}...")
        except RuntimeError as e:
            logger.error(f"Failed to analyze {level_name}: {e}. Skipping to next level to save pipeline.")
        
        # Tiny sleep to avoid 429 RPM limits on free tier
        if i < len(levels):
            time.sleep(2)

    logger.info("Synthesizing core workflows into final analysis...")
    synthesis_prompt = _build_ares_synthesis_prompt(all_screen_contexts, state_graph)
    synthesis_report = _call_api(synthesis_prompt)
    
    import json
    try:
        final_data = json.loads(synthesis_report)
        final_data["screen_contexts"] = all_screen_contexts
        return json.dumps(final_data, indent=2)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse synthesis JSON: {synthesis_report[:100]}...")
        return synthesis_report


def _build_prompt(screen_data):
    """Build the analysis prompt with screen data."""
    prompt = """
You are an expert mobile application analyst.
You are given a sequence of screens in chronological order. Each screen has a number, a filename, and the text extracted from it via OCR.

Your task is to produce a structured JSON object that maps the application's surface and workflows. Do not include markdown formatting like ```json, just output raw JSON.

Use the following JSON schema:
{
  "app_summary": "A brief overall summary of the application based on the screens.",
  "workflows": [
    {
      "start_screen": "filename or state ID",
      "end_screen": "filename or state ID",
      "user_action": "What the user did (e.g. tapped Login, scrolled down)",
      "description": "What this workflow accomplishes."
    }
  ],
  "screen_contexts": [
    {
      "screen_id": "filename or state ID",
      "type": "e.g. Splash Screen, Login, Dashboard",
      "context": "Detailed description of UI elements, buttons, and text on this screen."
    }
  ]
}

Data:
"""

    for screen in screen_data:
        prompt += f"\n--- Screen {screen['screen_number']}: {screen['filename']} ---\n"
        prompt += screen["extracted_text"]
        prompt += "\n"

    return prompt


def _build_ares_batch_prompt(screen_data, state_graph, level_name):
    """Build a prompt for a subset of ARES screens in a level."""
    prompt = f"""
You are a security researcher analyzing a subset of screens from an Android application.
You are currently analyzing screens from '{level_name}'.

To prevent hallucinations, here is the GLOBAL State Transition Graph for the entire application:
"""
    import json
    prompt += json.dumps(state_graph, indent=2) + "\n\n"

    prompt += """
Your task is to analyze ONLY the provided screens below, and extract their contextual meaning, UI elements, and any sensitive data. Keep in mind where they fit into the overall state graph.

Produce a JSON array containing the detailed context of EVERY SINGLE SCREEN provided. Do NOT skip any screens.
Do not output markdown block formatting, output raw JSON.

Use this JSON schema:
{
  "screen_contexts": [
    {
      "state_id": "filename or state ID",
      "type": "e.g. Dashboard, Settings",
      "context": "Detailed description of the screen's UI and data shown."
    }
  ]
}

### Provided Screens for Analysis
"""
    for screen in screen_data:
        prompt += f"\n--- Screen {screen['filename']} ---\n"
        prompt += screen["extracted_text"]
        prompt += "\n"

    return prompt


def _build_ares_synthesis_prompt(all_screen_contexts, state_graph):
    """Build a synthesis prompt to combine screen contexts into a final workflow analysis."""
    prompt = """
You are an expert mobile application analyst mapping the entire functional surface of an Android app.

We have processed the application's screens in batches and extracted their raw contexts into a massive JSON array. Below is the global State Transition Graph, and the extracted screen contexts array.

Your task is to synthesize these contexts into a SINGLE, cohesive Final Report in JSON format. Do not include markdown block formatting, output raw JSON.

CRITICAL: Do NOT output `screen_contexts`. We already have it. You must ONLY output `app_summary` and `core_workflows`.

Use this EXACT JSON schema:
{
  "app_summary": "Overall purpose of the app and a summary of what it does.",
  "core_workflows": [
    {
      "path": "e.g. State 0 -> State 10 -> State 12",
      "description": "What the user is doing in this flow.",
      "purpose": "Why this flow is important to the app's functionality."
    }
  ]
}

### State Transition Graph (JSON)
"""
    import json
    prompt += json.dumps(state_graph, indent=2) + "\n\n"

    prompt += "### Aggregated Screen Contexts\n\n"
    prompt += json.dumps(all_screen_contexts, indent=2)

    return prompt


def _build_ares_single_prompt(screen_data, state_graph):
    """Build a single massive prompt to analyze all ARES screens at once to save quota."""
    prompt = """
You are an expert mobile application analyst mapping the functional surface of an Android app.

To prevent hallucinations, here is the GLOBAL State Transition Graph for the entire application:
"""
    import json
    prompt += json.dumps(state_graph, indent=2) + "\n\n"

    prompt += """
Your task is to analyze ALL the provided screens below. Keep in mind where they fit into the overall state graph.

Produce a structured JSON object containing your analysis. Do NOT output markdown, just raw JSON.

Use the following JSON schema:
{
  "app_summary": "Overall purpose of the app and a summary of what it does.",
  "core_workflows": [
    {
      "path": "e.g. State 0 -> State 10 -> State 12",
      "description": "What the user is doing in this flow.",
      "purpose": "Why this flow is important to the app's functionality."
    }
  ],
  "screen_contexts": [
    {
      "state_id": "state number",
      "type": "e.g. Dashboard, Settings",
      "context": "Detailed description of the screen's UI and data shown."
    }
  ]
}

### Provided Screens for Analysis
"""
    for screen in screen_data:
        prompt += f"\n--- Screen {screen['filename']} ---\n"
        prompt += screen["extracted_text"]
        prompt += "\n"

    return prompt
