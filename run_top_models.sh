#!/bin/bash
# Script to sequentially boot up all 6 LLMs and run a full-app temperature sweep

MODELS=(
    "/home/apf/Documents/models/qwen/Qwen2.5-14B-Instruct-Q4_K_M.gguf"
    "/home/apf/Documents/models/mistral/Mistral-Nemo-Instruct-2407-Q4_K_M.gguf"
    "/home/apf/Documents/models/phi4/phi-4-Q4_K_M.gguf"
)

# Start logging
LOGFILE="/tmp/full_app_benchmark.log"
echo "Starting full-app multi-model benchmark at $(date)" > $LOGFILE

for MODEL in "${MODELS[@]}"; do
    echo "=======================================================" | tee -a $LOGFILE
    echo "Processing model: $MODEL" | tee -a $LOGFILE
    echo "=======================================================" | tee -a $LOGFILE

    # Ensure no old servers are running
    pkill -f llama-server
    sleep 3

    # Boot the server
    echo "-> Booting llama-server..." | tee -a $LOGFILE
    llama-server --model "$MODEL" -c 16384 --port 8001 --api-key "my_secret_token" > /tmp/llama_server_run.log 2>&1 &
    SERVER_PID=$!
    
    # Poll the server until it responds with 200 OK
    max_retries=600
    retries=0
    while ! curl -s -f http://127.0.0.1:8001/v1/models > /dev/null; do
        sleep 1
        retries=$((retries+1))
        if [ $retries -eq $max_retries ]; then
            echo "-> Error: Server failed to load model within 10 minutes." | tee -a $LOGFILE
            break
        fi
    done
    echo "-> Model successfully loaded! Took $retries seconds." | tee -a $LOGFILE

    # Run the benchmark script (no --levels means ALL levels)
    echo "-> Running benchmark sweep (0.0, 0.3, 0.7) for ALL levels..." | tee -a $LOGFILE
    ./pyscreen_env/bin/python benchmark.py --temperatures 0.0 0.3 0.7 --output-dir benchmark_results_v2 >> $LOGFILE 2>&1
    
    # Kill the server
    echo "-> Shutting down server (PID $SERVER_PID)..." | tee -a $LOGFILE
    kill -9 $SERVER_PID
    wait $SERVER_PID 2>/dev/null
    sleep 5
done

echo "=======================================================" | tee -a $LOGFILE
echo "All models successfully benchmarked across full app!" | tee -a $LOGFILE
