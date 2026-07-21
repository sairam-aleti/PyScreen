# Model Comparison — PyScreen Benchmark

Auto-updated each time `benchmark.py` runs. Each model is tested at multiple temperatures.

| Model | Best Time | Report Len | Best Temp | Score | All Temps | Tested At |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Mistral-Nemo-Instruct-2407-Q4_K_M | 115.85s | 13714 | 0.7 | 100/100 | t0.0=80pts / t0.3=10pts / t0.7=100pts | 2026-07-21 12:51 |
| Qwen2.5-14B-Instruct-Q4_K_M | 150.92s | 19288 | 0.0 | 100/100 | t0.0=100pts / t0.3=100pts / t0.7=80pts | 2026-07-21 12:42 |
| unknown | 26.02s | 0 | None | -1/100 |  | 2026-07-21 13:03 |

---

Full reports per model are in `benchmark_results/<model_name>/t<temp>_report.json`.
The OCR input (what all models received) is in `ocr_input.txt`.
