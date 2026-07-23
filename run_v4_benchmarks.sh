#!/bin/bash
# PyScreen V4 Benchmark Runner
# Runs the full benchmark sweep across all models (excluding 70B) in the background.

LOGFILE="/tmp/v4_benchmark_run.log"
echo "Starting V4 full-app multi-model benchmark at $(date)" > $LOGFILE

run_model_set() {
    local OUTPUT_DIR=$1
    shift
    local MODELS=("$@")

    for MODEL in "${MODELS[@]}"; do
        echo "=======================================================" | tee -a $LOGFILE
        echo "Processing model: $MODEL" | tee -a $LOGFILE
        echo "Output directory: $OUTPUT_DIR" | tee -a $LOGFILE
        echo "=======================================================" | tee -a $LOGFILE

        # Ensure no old servers are running
        pkill -f llama-server
        sleep 3

        # Boot the server (adjusting ctx size to 16384 which fits these models nicely)
        echo "-> Booting llama-server..." | tee -a $LOGFILE
        llama-server --model "$MODEL" -c 16384 --port 8001 --api-key "my_secret_token" > /tmp/llama_server_v4.log 2>&1 &
        SERVER_PID=$!
        
        # Wait for the server to load the model and bind to port
        echo "-> Waiting for model to load into VRAM..." | tee -a $LOGFILE
        sleep 25

        # Run the benchmark script, pushing output to specific dir
        echo "-> Running benchmark sweep (0.0, 0.3, 0.7)..." | tee -a $LOGFILE
        ./pyscreen_env/bin/python benchmark.py --temperatures 0.0 0.3 0.7 --output-dir "$OUTPUT_DIR" >> $LOGFILE 2>&1
        
        # Kill the server
        echo "-> Shutting down server (PID $SERVER_PID)..." | tee -a $LOGFILE
        kill -9 $SERVER_PID
        wait $SERVER_PID 2>/dev/null
        sleep 5
    done
}

MODELS_SMALL=(
    "/home/apf/Documents/models/llama/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    "/home/apf/Documents/models/mistral/Mistral-Nemo-Instruct-2407-Q4_K_M.gguf"
    "/home/apf/Documents/models/qwen/Qwen2.5-14B-Instruct-Q4_K_M.gguf"
    "/home/apf/Documents/models/phi/phi-4-Q4_K_M.gguf"
    "/home/apf/Documents/models/gemma2/gemma-2-9b-it-Q4_K_M.gguf"
    "/home/apf/Documents/models/deepseek/DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf"
)

MODELS_LARGE=(
    "/home/apf/Documents/models/qwen32b/Qwen2.5-32B-Instruct-Q4_K_M.gguf"
    "/home/apf/Documents/models/gemma2_27b/gemma-2-27b-it-Q4_K_M.gguf"
)

echo "Starting Small/Medium Models (8B-14B)..." | tee -a $LOGFILE
run_model_set "results_v4_8B_14B" "${MODELS_SMALL[@]}"

echo "Starting Large Models (27B-32B)..." | tee -a $LOGFILE
run_model_set "results_v4_27B_32B" "${MODELS_LARGE[@]}"

echo "=======================================================" | tee -a $LOGFILE
echo "All V4 benchmarks completed successfully!" | tee -a $LOGFILE
