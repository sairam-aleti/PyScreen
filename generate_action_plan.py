import os
import json
import logging
import time
import requests
from collections import defaultdict

from utils.llm_analyze import strip_markdown_json, LLAMA_CPP_HOST, LLAMA_CPP_API_KEY, DEFAULT_LLAMA_CPP_MODEL

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("action_planner")

def _call_api(prompt, schema):
    url = f"{LLAMA_CPP_HOST}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLAMA_CPP_API_KEY}",
    }
    payload = {
        "model": os.getenv("LLAMA_CPP_MODEL", DEFAULT_LLAMA_CPP_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "strict_extraction",
                "strict": True,
                "schema": schema
            }
        }
    }
    
    resp = requests.post(url, json=payload, headers=headers, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    if "choices" in data and len(data["choices"]) > 0:
        return data["choices"][0].get("message", {}).get("content", "")
    return ""

ACTION_PLAN_SCHEMA = {
  "type": "object",
  "properties": {
    "action_type": {"type": "string", "enum": ["tap", "scroll_down", "scroll_up", "input_text", "back", "home", "wait"]},
    "target_text": {"type": ["string", "null"]},
    "input_text": {"type": ["string", "null"]},
    "description": {"type": "string"}
  },
  "required": ["action_type", "target_text", "input_text", "description"]
}

def build_action_prompt(source_context, dest_context):
    prompt = f"""
You are an expert Android test automation engineer.
Your task is to determine the EXACT physical action the user took to transition from the Source Screen to the Destination Screen.

Choose ONE of the following action types:
- tap (requires target_text)
- scroll_down
- scroll_up
- input_text (requires target_text of the text field, and input_text for what to type)
- back (user pressed android back button)
- home (user pressed android home button)

### Source Screen Context:
Type: {source_context.get('type', 'Unknown')}
Details: {source_context.get('context', 'Unknown')}

### Destination Screen Context:
Type: {dest_context.get('type', 'Unknown')}
Details: {dest_context.get('context', 'Unknown')}

Output a JSON object with:
- action_type (string from the list above)
- target_text (the exact text or description of the UI element interacted with on the source screen, or null if not applicable)
- input_text (what text was typed, if action is input_text, else null)
- description (a human-readable explanation of the action)
"""
    return prompt

def generate_plan(final_output_path, state_graph_path, start_state="State 0", max_steps=10):
    logger.info(f"Loading data from {final_output_path} and {state_graph_path}")
    
    with open(final_output_path) as f:
        data = json.load(f)
        
    # Map 'State 0' -> context dict
    contexts = {}
    for ctx in data.get("screen_contexts", []):
        state_id = ctx.get("state_id", "")
        # e.g. "level_0/state_0.png" -> "State 0"
        basename = os.path.basename(state_id).replace(".png", "")
        if basename.startswith("state_"):
            formatted = basename.replace("state_", "State ")
            contexts[formatted] = ctx
            # also save original state_id for the output
            ctx["original_file"] = state_id

    # Parse state graph
    edges = defaultdict(list)
    with open(state_graph_path) as f:
        for line in f:
            if "->" in line:
                src, dst = line.strip().split(" -> ")
                edges[src].append(dst)

    # Find a simple linear path (DFS/greedy)
    path = []
    current = start_state
    for _ in range(max_steps):
        path.append(current)
        if current not in edges or not edges[current]:
            break
        # Just take the first outgoing edge for the primary path
        current = edges[current][0]
        if current in path: # avoid loops
            break

    if len(path) < 2:
        logger.error("Could not find a path with at least 2 states.")
        return

    logger.info(f"Generating action plan for path: {' -> '.join(path)}")

    action_plan = {
        "app_package": "org.quantumbadger.redreader",
        "app_name": "RedReader",
        "workflow_name": f"Generated Workflow from {path[0]} to {path[-1]}",
        "repeat_count": 1,
        "signal_data_collection": True,
        "steps": []
    }

    step_id = 1
    for i in range(len(path) - 1):
        src = path[i]
        dst = path[i+1]
        
        src_ctx = contexts.get(src)
        dst_ctx = contexts.get(dst)
        
        if not src_ctx or not dst_ctx:
            logger.warning(f"Missing context for {src} or {dst}, skipping...")
            continue
            
        logger.info(f"Step {step_id}: {src} -> {dst}")
        prompt = build_action_prompt(src_ctx, dst_ctx)
        
        try:
            response = _call_api(prompt, schema=ACTION_PLAN_SCHEMA)
            clean_json = strip_markdown_json(response)
            action_data = json.loads(clean_json)
            
            step = {
                "step_id": step_id,
                "from_state": src_ctx["original_file"],
                "to_state": dst_ctx["original_file"],
                "action_type": action_data["action_type"],
                "target": {
                    "match_strategy": "text_contains" if action_data["target_text"] else "none",
                    "text": action_data["target_text"],
                    "resource_id": None
                },
                "input_text": action_data.get("input_text"),
                "description": action_data["description"],
                "wait_after_ms": 2000,
                "expected_screen_type": dst_ctx.get("type", "Unknown")
            }
            action_plan["steps"].append(step)
            step_id += 1
            
        except Exception as e:
            logger.error(f"Failed to generate action for {src} -> {dst}: {e}")

    out_file = "action_plan.json"
    with open(out_file, "w") as f:
        json.dump(action_plan, f, indent=2)
    logger.info(f"Successfully wrote action plan to {out_file} with {len(action_plan['steps'])} steps.")

if __name__ == "__main__":
    generate_plan(
        final_output_path="results_1000_Qwen2.5-14B/final_output.json",
        state_graph_path="ARES_1000_state_graph.txt",
        start_state="State 0",
        max_steps=10
    )
