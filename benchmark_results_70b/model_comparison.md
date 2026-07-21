# Model Comparison — PyScreen Benchmark

Auto-updated each time `benchmark.py` runs. Each model is tested at multiple temperatures.

| Model | Best Time | Report Len | Best Temp | Score | All Temps | Tested At |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Meta-Llama-3.1-70B-Instruct-Q4_K_M | 1576.63s | 1021 | 0.0 | 50/100 | t0.0=50pts / t0.3=50pts / t0.7=50pts | 2026-07-19 01:22 |
| qwen2.5-72b-instruct-q4_k_m-00001-of-00012 | 2543.17s | 0 | None | -1/100 |  | 2026-07-19 00:04 |
| unknown | 26.02s | 0 | None | -1/100 |  | 2026-07-18 20:04 |

---

Full reports per model are in `benchmark_results/<model_name>/t<temp>_report.json`.
The OCR input (what all models received) is in `ocr_input.txt`.
