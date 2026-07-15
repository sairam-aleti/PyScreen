# Model Comparison — PyScreen Benchmark

Auto-updated each time `benchmark.py` runs. Each model is tested at multiple temperatures.

| Model | Best Time | Report Len | Best Temp | Score | All Temps | Tested At |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| DeepSeek-R1-Distill-Llama-8B-Q4_K_M | 178.28s | 9018 | 0.0 | 10/100 | t0.0=10pts / t0.3=10pts / t0.7=10pts | 2026-07-14 12:41 |
| Meta-Llama-3.1-8B-Instruct-Q4_K_M | 9.9s | 4232 | 0.0 | 89/100 | t0.0=89pts / t0.3=87pts / t0.7=79pts | 2026-07-11 19:29 |
| Mistral-Nemo-Instruct-2407-Q4_K_M | 19.95s | 5290 | 0.3 | 95/100 | t0.0=91pts / t0.3=95pts / t0.7=95pts | 2026-07-11 19:06 |
| Qwen2.5-14B-Instruct-Q4_K_M | 84.39s | 15502 | 0.0 | 100/100 | t0.0=100pts | 2026-07-15 16:10 |
| gemma-2-9b-it-Q4_K_M | 109.16s | 0 | None | -1/100 |  | 2026-07-14 12:31 |
| phi-4-Q4_K_M | 25.16s | 4581 | 0.3 | 94/100 | t0.0=92pts / t0.3=94pts / t0.7=94pts | 2026-07-11 19:32 |
| unknown | 26.02s | 0 | None | -1/100 |  | 2026-07-14 12:25 |

---

Full reports per model are in `benchmark_results/<model_name>/t<temp>_report.json`.
The OCR input (what all models received) is in `ocr_input.txt`.
