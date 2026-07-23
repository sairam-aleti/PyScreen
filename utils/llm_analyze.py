"""
LLM analysis module for PyScreen.
Supports three backends:
  - "gemini"    : Google Gemini cloud API (requires GEMINI_API_KEY)
  - "ollama"    : Local Ollama server (requires Ollama running)
  - "llama_cpp" : Local llama.cpp server (llama-server, OpenAI-compatible API)

Set the LLM_BACKEND env var to choose. Default is "gemini".
"""
import os
import re
import time
import logging
import json
import concurrent.futures


def strip_markdown_json(text):
    """Strip markdown code fences from LLM output to extract raw JSON.
    Handles: ```json ... ```, ``` ... ```, and leading/trailing whitespace.
    """
    text = text.strip()
    # Try to extract from ```json ... ``` or ``` ... ``` blocks
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Try to extract from ```json ... ``` blocks with array
    match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # If no code fences, try to find raw JSON object
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def deterministic_verify(ocr_text, context_str):
    """Deterministic keyword-matching verifier. Does NOT use an LLM.
    
    Extracts significant words from the generated context and checks
    how many of them actually appear in the original OCR text.
    Returns a dict with verified=True/False and a cleaned confidence score.
    """
    if not ocr_text or not context_str:
        return {"verified": True, "ocr_coverage": 0.0}
    
    # Normalize both texts
    ocr_lower = ocr_text.lower()
    ctx_lower = context_str.lower()
    
    # Extract significant words from context (3+ chars, not stopwords)
    stopwords = {
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
        'had', 'her', 'was', 'one', 'our', 'out', 'has', 'have', 'each',
        'with', 'this', 'that', 'from', 'they', 'been', 'said', 'will',
        'into', 'also', 'than', 'them', 'other', 'some', 'there', 'which',
        'their', 'about', 'would', 'these', 'could', 'does', 'most',
        'screen', 'displays', 'shows', 'includes', 'provides', 'option',
        'options', 'button', 'text', 'page', 'menu', 'user', 'section',
        'application', 'named', 'various', 'below', 'above', 'such',
        'state', 'level', 'type', 'string', 'integer', 'context',
    }
    
    ctx_words = set()
    for word in re.findall(r'[a-z]{3,}', ctx_lower):
        if word not in stopwords:
            ctx_words.add(word)
    
    if not ctx_words:
        return {"verified": True, "ocr_coverage": 1.0}
    
    # Check how many context words appear in the OCR text
    found = sum(1 for w in ctx_words if w in ocr_lower)
    coverage = found / len(ctx_words) if ctx_words else 1.0
    
    return {
        "verified": coverage >= 0.15,  # At least 15% of keywords found in OCR
        "ocr_coverage": round(coverage, 3),
        "total_keywords": len(ctx_words),
        "matched_keywords": found,
    }



BATCH_SCHEMA = {
  "type": "object",
  "properties": {
    "screen_contexts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "state_id": {"type": "string"},
          "type": {"type": "string"},
          "context": {"type": "string"},
          "confidence_score": {"type": "integer"}
        },
        "required": ["state_id", "type", "context", "confidence_score"]
      }
    }
  },
  "required": ["screen_contexts"]
}

SYNTHESIS_SCHEMA = {
  "type": "object",
  "properties": {
    "app_summary": {"type": "string"},
    "core_workflows": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "description": {"type": "string"},
          "purpose": {"type": "string"}
        },
        "required": ["path", "description", "purpose"]
      }
    }
  },
  "required": ["app_summary", "core_workflows"]
}

SINGLE_SCHEMA = {
  "type": "object",
  "properties": {
    "app_summary": {"type": "string"},
    "core_workflows": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "description": {"type": "string"},
          "purpose": {"type": "string"}
        },
        "required": ["path", "description", "purpose"]
      }
    },
    "screen_contexts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "state_id": {"type": "string"},
          "type": {"type": "string"},
          "context": {"type": "string"},
          "confidence_score": {"type": "integer"}
        },
        "required": ["state_id", "type", "context", "confidence_score"]
      }
    }
  },
  "required": ["app_summary", "core_workflows", "screen_contexts"]
}

AUDITOR_SCHEMA = {
  "type": "object",
  "properties": {
    "state_id": {"type": "string"},
    "type": {"type": "string"},
    "context": {"type": "string"},
    "confidence_score": {"type": "integer"}
  },
  "required": ["state_id", "type", "context", "confidence_score"]
}


# Default models per backend
DEFAULT_OLLAMA_MODEL = "gemma3:27b"
DEFAULT_LLAMA_CPP_MODEL = "Qwen2.5-32B-Instruct-Q4_K_M"

# Backend selection (Default to llama_cpp instead of gemini)
LLM_BACKEND = os.getenv("LLM_BACKEND", "llama_cpp").strip().lower()

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAYS = [30, 60, 120]  # seconds between retries
REQUEST_TIMEOUT = 120  # seconds

# Local server hosts
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
LLAMA_CPP_HOST = os.getenv("LLAMA_CPP_HOST", "http://localhost:8001").strip()
LLAMA_CPP_API_KEY = os.getenv("LLAMA_CPP_API_KEY", "my_secret_token").strip()


def analyze_screens(screen_data, model=None, benchmark_callback=None, state_graph=None, **kwargs):
    """
    Send extracted screen text data to a local LLM for a detailed
    user-journey and security analysis report.

    Supports two local backends (set via LLM_BACKEND env var):
      - "llama_cpp": Local llama.cpp server (OpenAI-compatible)
      - "ollama": Local Ollama server

    Args:
        screen_data: List of dicts with 'screen_number', 'filename', 'extracted_text'
        model: Model name to use. Defaults to env var or built-in default.
        benchmark_callback: Optional callable(model, input_tokens, output_tokens, request_time,
                            retries, success, error) for metrics collection.
        state_graph: Optional dict representing the app's state transition graph.

    Returns:
        The analysis report as a string.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    backend = LLM_BACKEND
    logger.info(f"Using LLM backend: {backend}")

    if backend == "ollama":
        import requests as _requests
        model_name = model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        logger.info(f"Ollama model: {model_name} at {OLLAMA_HOST}")
    elif backend == "llama_cpp":
        import requests as _requests
        model_name = model or os.getenv("LLAMA_CPP_MODEL", DEFAULT_LLAMA_CPP_MODEL)
        logger.info(f"llama.cpp model: {model_name} at {LLAMA_CPP_HOST}")
    else:
        raise ValueError(f"Unknown LLM_BACKEND: '{backend}'. Use 'llama_cpp' or 'ollama'.")

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
            "stream": False,
        }

        # If a strict schema is provided, force grammar constraint
        if kwargs.get("schema"):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "strict_extraction",
                    "strict": True,
                    "schema": kwargs["schema"]
                }
            }
        else:
            payload["response_format"] = {"type": "json_object"}

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

        return strip_markdown_json(text)

    def _call_api(prompt, schema=None):
        logger.info(f"Calling LLM ({backend}: {model_name})...")
        logger.debug(f"Prompt length: {len(prompt)} characters")

        if schema:
            kwargs["schema"] = schema

        if backend == "ollama":
            return _call_ollama(prompt)
        elif backend == "llama_cpp":
            return _call_llama_cpp(prompt)
        else:
             raise ValueError("Only local backends (llama_cpp, ollama) are supported.")

    if not state_graph:
        prompt = _build_prompt(screen_data)
        return _call_api(prompt, schema=SINGLE_SCHEMA)

    # ARES mode: Process by level
    logger.info("Grouping screens by level for analysis...")
    from collections import defaultdict
    import time
    levels = defaultdict(list)
    for screen in screen_data:
        # Assuming filename is something like 'level_8/state_0.png'
        if '/' in screen['filename'] or '\\' in screen['filename']:
            level_name = screen['filename'].replace('\\', '/').split('/')[0]
        else:
            level_name = 'unknown_level'
        levels[level_name].append(screen)

    all_screen_contexts = []
    
    def process_level(level_info):
        i, level_name, level_screens = level_info
        logger.info(f"  Analyzing level {i}/{len(levels)}: {level_name} ({len(level_screens)} screens)...")
        prompt = _build_ares_batch_prompt(level_screens, state_graph, level_name)
        
        try:
            report = _call_api(prompt, schema=BATCH_SCHEMA)
            clean_report = strip_markdown_json(report)
            data = json.loads(clean_report)
            verified_contexts = []
            
            if "screen_contexts" in data:
                raw_contexts = data["screen_contexts"]
                for ctx in raw_contexts:
                    ocr_text = ""
                    for s in level_screens:
                        if s['filename'] == ctx.get('state_id'):
                            ocr_text = s['extracted_text']
                            break
                            
                    if not ocr_text:
                        verified_contexts.append(ctx)
                        continue
                        
                    verify_result = deterministic_verify(ocr_text, ctx.get('context', ''))
                    
                    if verify_result["verified"]:
                        ocr_cov = verify_result["ocr_coverage"]
                        if ocr_cov < 0.3:
                            ctx["confidence_score"] = min(ctx.get("confidence_score", 50), 50)
                            ctx["verification_note"] = f"Low OCR coverage ({ocr_cov:.0%}). Context may contain inferred elements."
                        verified_contexts.append(ctx)
                    else:
                        logger.warning(f"    ⚠ Verifier REJECTED {ctx.get('state_id')}: OCR coverage {verify_result['ocr_coverage']:.0%}")
                        ctx["confidence_score"] = 20
                        ctx["verification_note"] = f"FLAGGED: Only {verify_result['matched_keywords']}/{verify_result['total_keywords']} keywords found in OCR."
                        verified_contexts.append(ctx)
            return verified_contexts
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON for {level_name}")
            return []
        except RuntimeError as e:
            logger.error(f"Failed to analyze {level_name}: {e}")
            return []
            
    # Smart batching: If more than 3 levels, run concurrently (up to 3 parallel workers)
    level_list = [(i+1, k, v) for i, (k, v) in enumerate(levels.items())]
    if len(levels) > 3:
        logger.info(f"Processing {len(levels)} levels concurrently (Thread pool)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(process_level, level_list))
            for res in results:
                all_screen_contexts.extend(res)
    else:
        logger.info(f"Processing {len(levels)} levels sequentially...")
        for level_info in level_list:
            res = process_level(level_info)
            all_screen_contexts.extend(res)
            time.sleep(1)

    logger.info("Synthesizing core workflows into final analysis...")
    synthesis_prompt = _build_ares_synthesis_prompt(all_screen_contexts, state_graph)
    synthesis_report = _call_api(synthesis_prompt, schema=SYNTHESIS_SCHEMA)
    
    # Apply markdown stripping before JSON parse
    clean_synthesis = strip_markdown_json(synthesis_report)
    import json
    try:
        final_data = json.loads(clean_synthesis)
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
      "context": "Detailed description of UI elements, buttons, and text on this screen.",
      "confidence_score": 95
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
      "context": "Detailed description of the screen's UI and data shown.",
      "confidence_score": 90
    }
  ]
}

### CRITICAL: CONFIDENCE SCORING
Assign a `confidence_score` (0-100) based on the quality of the OCR. If the OCR is a mess of random characters and you cannot reliably determine the UI elements, score it below 50. If the text is clean and the UI is obvious, score it 90+.

### GOLDEN EXAMPLE
**OCR Input:**
[Settings Menu]
[Profile]
[Logout]

**Ideal JSON Output:**
{
  "screen_contexts": [
    {
      "state_id": "level_1/state_1.png",
      "type": "Settings",
      "context": "The screen displays a basic Settings Menu with two clickable options: Profile and Logout.",
      "confidence_score": 98
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

CRITICAL INSTRUCTIONS FOR CORE WORKFLOWS:
1. You MUST extract EVERY SINGLE distinct workflow path (level) present in the state graph.
2. DO NOT summarize them into just 2 or 3 workflows. If there are 10 unique paths in the graph, you MUST output at least 10 core_workflows. 
3. For EVERY state transition, you MUST describe the SPECIFIC PHYSICAL USER ACTION that causes it.
   - BAD: "The user transitions to State 10"
   - BAD: "The user moves to the settings screen"
   - GOOD: "The user taps the 'Accept' button on the user agreement dialog, which navigates to the Front Page (State 11)"
   - GOOD: "The user presses the Android back button to return to the subreddit list (State 13)"
   - GOOD: "The user scrolls down and taps the 'Appearance' option in the Settings menu to open font settings (State 20)"
4. Use the screen_contexts to identify WHAT buttons, links, and menu items are physically visible on each screen. Reference them by name.
5. If the state graph shows a backward transition (e.g., State 12 -> State 10), describe it as "the user presses Back" or "the user taps Close/Cancel".

CRITICAL: Do NOT output `screen_contexts`. We already have it. You must ONLY output `app_summary` and `core_workflows`.

### GOLDEN WORKFLOW EXAMPLE
{
  "path": "State 0 -> State 10 -> State 11",
  "description": "Step 1: The user opens the app and sees the User Agreement screen (State 0) which displays the RedReader terms. Step 2: The user taps the 'Accept' button at the bottom of the agreement dialog, navigating to the Reddit User Agreement confirmation (State 10). Step 3: The user taps 'I Agree' to confirm acceptance, which loads the Front Page (State 11) showing a list of subscribed subreddits like 'art', 'askreddit', and 'aww'.",
  "purpose": "First-time user onboarding flow that gates access behind agreement acceptance."
}

Use this EXACT JSON schema:
{
  "app_summary": "Overall purpose of the app and a detailed summary of what it does.",
  "core_workflows": [
    {
      "path": "e.g. State 0 -> State 10 -> State 12",
      "description": "A step-by-step breakdown where EVERY transition describes the exact button/link/action the user physically performs. Never say 'transitions to' — always say what was tapped/pressed/scrolled.",
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
      "context": "Detailed description of the screen's UI and data shown.",
      "confidence_score": 90
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

def _build_auditor_prompt(ocr_text, generated_json):
    """Build a prompt for the Auditor Pass to verify and scrub hallucinations."""
    prompt = f"""
You are a strict security Auditor. Your job is to verify that a generated UI context perfectly matches the physical OCR text extracted from an Android screen.

You must scrub any hallucinated UI elements, buttons, or features that were hallucinated by the previous model.

### Original OCR Text
{ocr_text}

### Generated Context (To Be Audited)
{generated_json}

CRITICAL INSTRUCTIONS:
1. Compare the 'context' field against the Original OCR.
2. If the 'context' describes buttons, menus, or features NOT present in the OCR, REMOVE THEM.
3. If the 'context' is mostly accurate, keep it.
4. Output the corrected JSON object. Keep the 'state_id' the same. Update 'confidence_score' if the OCR is exceptionally messy.

Use this EXACT JSON schema:
{{
  "state_id": "string",
  "type": "string",
  "context": "string (scrubbed of hallucinations)",
  "confidence_score": integer
}}
"""
    return prompt

