# Model Comparison — PyScreen Benchmark

Auto-updated each time `benchmark.py` runs. Each model is tested at multiple temperatures.

| Model | Best Time | Report Len | Best Temp | Score | All Temps | Tested At |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Meta-Llama-3.1-8B-Instruct-Q4_K_M | 0.0s | 0 | None | -1/100 |  | 2026-07-24 01:37 |
| Mistral-Nemo-Instruct-2407-Q4_K_M | 0.0s | 0 | None | -1/100 |  | 2026-07-24 01:38 |
| Qwen2.5-14B-Instruct-Q4_K_M | 0.0s | 0 | None | -1/100 |  | 2026-07-24 01:38 |
| unknown | 0.0s | 0 | None | -1/100 |  | 2026-07-24 01:40 |

---

Full reports per model are in `benchmark_results/<model_name>/t<temp>_report.json`.
The OCR input (what all models received) is in `ocr_input.txt`.
