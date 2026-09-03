#!/usr/bin/env python3
import os
import cv2
import time
import json
import psutil
from datetime import datetime

from utils.text_compute import text_compute
from utils.llm_analyze import analyze_screens

def main():
    print(f"[{datetime.now().isoformat()}] Starting massive 1000-state end-to-end benchmark...")
    
    start_total = time.time()
    
    # 1. Load the 1000 physical frames
    print("[1] Loading 1000 frames into memory...")
    start_load = time.time()
    frames_dir = "ARES_1000_screenshots"
    image_files = sorted([f for f in os.listdir(frames_dir) if f.endswith(".png")], 
                         key=lambda x: int(x.split('_')[1].split('.')[0]))
    
    all_frames = []
    # We will simulate levels by dividing into batches of 20 here for the filename, 
    # since llm_analyze groups by level name embedded in filename.
    for i, filename in enumerate(image_files):
        level_idx = i // 20
        # Pretend it's in a level directory so the batching logic in llm_analyze works out of the box
        pseudo_filename = f"level_{level_idx}/{filename}"
        filepath = os.path.join(frames_dir, filename)
        frame = cv2.imread(filepath)
        if frame is not None:
            all_frames.append((pseudo_filename, frame))
            
    print(f"Loaded {len(all_frames)} frames in {time.time() - start_load:.2f} seconds.")
    
    # 2. Parse the synthetic state graph
    print("[2] Parsing synthetic state graph...")
    state_graph = {}
    with open("ARES_1000_state_graph.txt", "r") as f:
        for line in f:
            if "->" in line:
                parts = line.strip().split("->")
                src = parts[0].replace("State ", "").strip()
                dst = parts[1].replace("State ", "").strip()
                if src not in state_graph:
                    state_graph[src] = {"transitions": []}
                state_graph[src]["transitions"].append({"to_state": dst})
                
    # 3. OCR Phase
    print("\n=======================================================")
    print("[3] Initiating Phase 1: CPU OCR Processing (1000 images)")
    print("=======================================================")
    start_ocr = time.time()
    
    # Run OpenCV + Tesseract
    # To prevent blowing up memory with 1000 massive strings, text_compute writes to disk and returns it.
    result = text_compute(all_frames, disable_analysis=True, output_dir="results_1000_benchmark")
    screen_data = result["screen_data"]
    
    ocr_time = time.time() - start_ocr
    print(f"OCR Phase Complete. Time taken: {ocr_time:.2f} seconds ({ocr_time/1000:.3f}s per image).")
    
    # 4. LLM Phase
    print("\n=======================================================")
    print("[4] Initiating Phase 2 & 3: LLM Batching & Synthesis")
    print("=======================================================")
    start_llm = time.time()
    
    # Tracking Variables
    llm_metrics = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "failed_calls": 0
    }
    
    def my_callback(model, input_tokens, output_tokens, request_time, retries, success, error):
        llm_metrics["calls"] += 1
        if success:
            llm_metrics["input_tokens"] += input_tokens
            llm_metrics["output_tokens"] += output_tokens
        else:
            llm_metrics["failed_calls"] += 1

    try:
        report = analyze_screens(
            screen_data=screen_data,
            state_graph=state_graph,
            temperature=0.0,
            benchmark_callback=my_callback
        )
        llm_time = time.time() - start_llm
        print(f"LLM Phase Complete. Time taken: {llm_time:.2f} seconds.")
        
        # Save output
        with open("results_1000_benchmark/final_output.json", "w") as f:
            f.write(report)
            
    except Exception as e:
        llm_time = time.time() - start_llm
        print(f"LLM Phase failed after {llm_time:.2f} seconds: {e}")
        report = ""
    
    total_time = time.time() - start_total
    
    # 5. Output Final Matrix
    print("\n=======================================================")
    print("                FINAL PERFORMANCE MATRIX                 ")
    print("=======================================================")
    print(f"Total States Processed : {len(all_frames)}")
    print(f"Total Batches (est)    : {len(all_frames) // 20}")
    print(f"OpenCV + OCR Time      : {ocr_time:.2f} seconds")
    print(f"LLM Inference Time     : {llm_time:.2f} seconds")
    print(f"Total Pipeline Time    : {total_time:.2f} seconds")
    print("-------------------------------------------------------")
    print(f"Total LLM API Calls    : {llm_metrics['calls']}")
    print(f"Total Input Tokens     : {llm_metrics['input_tokens']}")
    print(f"Total Output Tokens    : {llm_metrics['output_tokens']}")
    print(f"Failed API Calls       : {llm_metrics['failed_calls']}")
    print("-------------------------------------------------------")
    print(f"Output Report Size     : {len(report)} characters")
    print("=======================================================")
    print("Benchmark completed. Output saved to results_1000_benchmark/")

if __name__ == "__main__":
    main()
