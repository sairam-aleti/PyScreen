#!/bin/bash

# Configuration
MODELS_DIR="/home/apf/Documents/models/large_models"
PORT=8001
CTX_SIZE=16384
API_KEY="my_secret_token"
OUTPUT_DIR="benchmark_results_70b"

# Define models to run
MODELS=(
    "qwen2.5-72b-instruct-q4_k_m-00001-of-00012.gguf"
    "Meta-Llama-3.1-70B-Instruct-Q4_K_M.gguf"
)

# Colors for nice output
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

mkdir -p "$OUTPUT_DIR"

for model_file in "${MODELS[@]}"; do
    model_path="$MODELS_DIR/$model_file"
    
    # Verify model exists
    if [ ! -f "$model_path" ]; then
        echo -e "\n${CYAN}=======================================================${NC}"
        echo -e "${CYAN}Skipping missing model: $model_file${NC}"
        echo -e "${CYAN}=======================================================${NC}"
        continue
    fi

    echo -e "\n${GREEN}=======================================================${NC}"
    echo -e "${GREEN}Processing model: $model_path${NC}"
    echo -e "${GREEN}=======================================================${NC}"

    # 1. Start the server
    echo "-> Booting llama-server..."
    llama-server --model "$model_path" -c $CTX_SIZE --port $PORT --api-key "$API_KEY" > /tmp/llama_server.log 2>&1 &
    SERVER_PID=$!

    # Give server time to load the model into memory
    echo "-> Waiting for massive model to load into RAM/VRAM..."
    
    # Poll the server until it responds with 200 OK (meaning model is fully loaded)
    max_retries=600 # 10 minutes max wait
    retries=0
    while ! curl -s -f http://127.0.0.1:$PORT/v1/models > /dev/null; do
        sleep 1
        retries=$((retries+1))
        if [ $retries -eq $max_retries ]; then
            echo "-> Error: Server failed to load model within 10 minutes."
            break
        fi
    done
    echo "-> Model successfully loaded! Took $retries seconds."

    # 2. Run the benchmarking script for temperatures 0.0, 0.3, 0.7
    echo "-> Running benchmark sweep (0.0, 0.3, 0.7)..."
    ./pyscreen_env/bin/python benchmark.py --temperatures 0.0 0.3 0.7 --output-dir "$OUTPUT_DIR"

    # 3. Kill server
    echo "-> Shutting down server (PID $SERVER_PID)..."
    kill $SERVER_PID
    wait $SERVER_PID 2>/dev/null
    
    # Extra cleanup just in case
    pkill -f llama-server
    sleep 5
done

echo -e "\n${GREEN}=======================================================${NC}"
echo -e "${GREEN}All 70B models successfully benchmarked!${NC}"
echo -e "${GREEN}Results saved to $OUTPUT_DIR${NC}"
