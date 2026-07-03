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


def analyze_screens(screen_data, model=None, benchmark_callback=None, state_graph=None):
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
            "temperature": 1.0,
            "top_p": 0.95,
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

    mini_reports = []
    logger.info(f"Processing {len(levels)} levels sequentially to avoid server timeouts...")
    for i, (level_name, level_screens) in enumerate(levels.items(), 1):
        logger.info(f"  Analyzing level {i}/{len(levels)}: {level_name} ({len(level_screens)} screens)...")
        prompt = _build_ares_batch_prompt(level_screens, state_graph, level_name)
        try:
            report = _call_api(prompt)
            mini_reports.append(f"### Level: {level_name}\n\n{report}")
        except RuntimeError as e:
            logger.error(f"Failed to analyze {level_name}: {e}. Skipping to next level to save pipeline.")
            mini_reports.append(f"### Level: {level_name}\n\n(Analysis skipped due to API server timeout)")
        
        # Tiny sleep to avoid 429 RPM limits on free tier
        if i < len(levels):
            time.sleep(2)

    logger.info("Synthesizing mini-reports into final analysis...")
    synthesis_prompt = _build_ares_synthesis_prompt(mini_reports, state_graph)
    return _call_api(synthesis_prompt)


def _build_prompt(screen_data):
    """Build the analysis prompt with screen data."""
    prompt = """
You are a security researcher analyzing screenshots captured from an Android mobile application.

You are given a sequence of screens in chronological order. Each screen has a number, a filename, and the text extracted from it via OCR.

Your task is to produce a DETAILED and PINPOINT analysis report with the following structure:

---

## Step 1: Screen-by-Screen Analysis

For EACH screen:
- **Screen Type:** Identify what kind of screen it is (e.g., Splash Screen, Login Page, Home Dashboard, Settings, Permission Dialog, etc.)
- **Description:** Describe in detail what is visible on this screen based on the extracted text. Mention specific UI elements, buttons, labels, input fields, and any data shown.
- **Key Observations:** Note anything security-relevant: permissions requested, data displayed (emails, usernames, account info), network indicators, toggles, or sensitive actions.

## Step 2: Transition Analysis

For EACH pair of consecutive screens:
- **What Changed:** Precisely describe what text appeared, disappeared, or changed between the two screens.
- **Inferred User Action:** Based on the changes, deduce exactly what the user did (e.g., "Tapped the 'Login' button", "Scrolled down", "Granted location permission", "Navigated to Settings > Privacy").
- **Data Exposure Risk:** Flag if this transition likely triggered any data being sent, stored, or exposed (e.g., login credentials submitted, location access granted, personal info displayed).

## Step 3: User Journey Timeline

Build a numbered, chronological timeline of the entire user journey. Each entry should include:
- The screen number
- The sequence position
- A one-line summary of what happened

## Step 4: Final Assessment

- **What is the user trying to achieve?** Summarize the user's overall goal.
- **What sensitive data or permissions were involved?** List all sensitive data points observed (credentials, personal info, device IDs, etc.) and permissions requested/granted.
- **Security-relevant actions:** Highlight any moments where data was likely transmitted, stored, or made accessible to third parties.

---

Important:
- Be thorough and specific. Do NOT produce vague summaries.
- Reference screen numbers and filenames in your analysis.
- Focus on security-relevant details since this is for a side-channel attack research project.
- If the OCR text is noisy or incomplete, note that and make your best inference.

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

Produce a mini-report with:
1. **Screen-by-Screen Breakdown:** For each screen, what is its purpose and what data is visible?
2. **Level Context:** How do these screens relate to each other within this level?

### Provided Screens for Analysis
"""
    for screen in screen_data:
        prompt += f"\n--- Screen {screen['filename']} ---\n"
        prompt += screen["extracted_text"]
        prompt += "\n"

    return prompt


def _build_ares_synthesis_prompt(mini_reports, state_graph):
    """Build a synthesis prompt to combine mini-reports into a final analysis."""
    prompt = """
You are a security researcher mapping the entire functional surface of an Android mobile application to identify privacy and security risks.

We have processed the application's screens in batches. Below are the mini-reports for each level of the application, along with the global State Transition Graph.

Your task is to synthesize these mini-reports into a SINGLE, cohesive Final Analysis Report. Do NOT just summarize the mini-reports. Connect the dots using the State Graph to figure out the critical workflows.

Produce a DETAILED analysis report with the following structure:

---

## Step 1: App Surface Mapping
- **Core Workflows:** Identify the main user journeys across the app (e.g., "States 0->1->2 represent User Login"). Use the State Graph to prove these connections.
- **App Purpose:** What is the overall purpose of this app?

## Step 2: Critical Workflows & Risk Assessment
Highlight the most security-sensitive paths in the graph. For each:
- Describe the path (e.g., "Path: State A -> State B -> State C")
- Explain the security or privacy implications of this workflow.
- Detail what data is likely transmitted or collected during this flow.

## Step 3: Final Assessment
- **What is the user trying to achieve?**
- **What sensitive data or permissions were involved?** List all sensitive data points observed and permissions requested/granted.
- **Security-relevant actions:** Highlight any moments where data was likely transmitted or stored.

---

### State Transition Graph (JSON)
"""
    import json
    prompt += json.dumps(state_graph, indent=2) + "\n\n"

    prompt += "### Mini-Reports by Level\n\n"
    for report in mini_reports:
        prompt += report + "\n"

    return prompt


def _build_ares_single_prompt(screen_data, state_graph):
    """Build a single massive prompt to analyze all ARES screens at once to save quota."""
    prompt = """
You are a security researcher mapping the entire functional surface of an Android mobile application to identify privacy and security risks.

To prevent hallucinations, here is the GLOBAL State Transition Graph for the entire application:
"""
    import json
    prompt += json.dumps(state_graph, indent=2) + "\n\n"

    prompt += """
Your task is to analyze ALL the provided screens below. Keep in mind where they fit into the overall state graph.

Produce a DETAILED analysis report with the following structure:

---

## Step 1: App Surface Mapping
- **Core Workflows:** Identify the main user journeys across the app (e.g., "States 0->1->2 represent User Login"). Use the State Graph to prove these connections.
- **App Purpose:** What is the overall purpose of this app?

## Step 2: Critical Workflows & Risk Assessment
Highlight the most security-sensitive paths in the graph. For each:
- Describe the path (e.g., "Path: State A -> State B -> State C")
- Explain the security or privacy implications of this workflow.
- Detail what data is likely transmitted or collected during this flow.

## Step 3: Final Assessment
- **What is the user trying to achieve?**
- **What sensitive data or permissions were involved?** List all sensitive data points observed and permissions requested/granted.
- **Security-relevant actions:** Highlight any moments where data was likely transmitted or stored.

---

### Provided Screens for Analysis
"""
    for screen in screen_data:
        prompt += f"\n--- Screen {screen['filename']} ---\n"
        prompt += screen["extracted_text"]
        prompt += "\n"

    return prompt
