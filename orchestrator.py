import json
import time
import logging
import requests
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("orchestrator")

# Change this to the IP of the Android device running Panda/Blurr
# If running on emulator or via ADB forward, it might be localhost:8080
PANDA_API_BASE = "http://localhost:8080" 

def send_action_to_panda(step):
    """
    Sends a single action step to Panda's REST API and returns the result.
    """
    url = f"{PANDA_API_BASE}/api/v1/execute"
    logger.info(f"Executing Step {step['step_id']}: {step['description']}")
    
    payload = {
        "action_type": step["action_type"],
        "target": step["target"],
        "input_text": step.get("input_text")
    }
    
    try:
        start_time = time.time()
        response = requests.post(url, json=payload, timeout=30)
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                logger.info(f"✅ Success ({elapsed:.2f}s): {result.get('message', 'Action completed')}")
                return True, result
            else:
                logger.error(f"❌ Failed ({elapsed:.2f}s): {result.get('error', 'Unknown error')}")
                return False, result
        else:
            logger.error(f"❌ HTTP Error {response.status_code}: {response.text}")
            return False, {"error": f"HTTP {response.status_code}"}
            
    except requests.exceptions.ConnectionError:
        logger.error(f"❌ Connection Error: Could not reach Panda at {PANDA_API_BASE}.")
        logger.error("Make sure the Panda app is running on the device and 'adb forward tcp:8080 tcp:8080' is set.")
        return False, {"error": "Connection Refused"}
    except requests.exceptions.Timeout:
        logger.error("❌ Timeout: Panda took too long to respond.")
        return False, {"error": "Timeout"}

def run_workflow(plan_path, iterations=1):
    try:
        with open(plan_path, 'r') as f:
            plan = json.load(f)
    except FileNotFoundError:
        logger.error(f"Action plan not found at {plan_path}. Run generate_action_plan.py first.")
        return
        
    logger.info(f"Loaded workflow: {plan.get('workflow_name')}")
    logger.info(f"Total steps: {len(plan.get('steps', []))}")
    
    for i in range(iterations):
        logger.info(f"--- Starting Iteration {i+1}/{iterations} ---")
        
        if plan.get("signal_data_collection"):
            logger.info("Signal: STARTING DATA COLLECTION")
            # Here you would trigger your side-channel script
            # subprocess.run(["./start_collection.sh"])
            
        success = True
        for step in plan.get("steps", []):
            step_success, result = send_action_to_panda(step)
            if not step_success:
                logger.error(f"Workflow aborted at step {step['step_id']} during iteration {i+1}.")
                success = False
                break
                
            # Wait before next step as defined in the plan
            wait_ms = step.get("wait_after_ms", 1000)
            logger.debug(f"Waiting {wait_ms}ms...")
            time.sleep(wait_ms / 1000.0)
            
        if plan.get("signal_data_collection"):
            logger.info("Signal: STOPPING DATA COLLECTION")
            # Here you would trigger your side-channel script
            # subprocess.run(["./stop_collection.sh"])
            
        if not success:
            logger.warning("Iteration failed. Proceeding to next iteration may cause issues if app state is not reset.")
            break
            
    logger.info("Orchestrator finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PyScreen-Panda Orchestrator")
    parser.add_argument("--plan", default="action_plan.json", help="Path to action plan JSON")
    parser.add_argument("--iterations", type=int, default=1, help="Number of times to repeat the workflow")
    args = parser.parse_args()
    
    run_workflow(args.plan, args.iterations)
