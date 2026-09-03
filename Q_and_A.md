# Persistent Q&A Log

This document serves as a persistent record of all your queries and my answers throughout our project. Whenever you ask a question, I will append the answer here so you can easily reference it later.

---

## Q1: What is the basis for choosing these specific models?

**Answer:**
We selected these models based on three primary criteria:
1. **Hardware Constraints (24GB VRAM):** All chosen models (ranging from 8B to 31B parameters) can comfortably fit into your 24GB VRAM when using `Q4_K_M` GGUF quantization. This ensures we don't encounter Out-Of-Memory (OOM) errors during inference, while still leaving enough VRAM for the context window.
2. **Specialized Capabilities:** We targeted the most capable architectures available in the 2025/2026 local open-weights ecosystem:
    * **Qwen 2.5 (14B):** Highly regarded for strict instruction-following and structured output.
    * **Mistral Nemo (12B):** Known as the "sweet spot" for balancing blazing speed with deep, creative analytical capabilities.
    * **Phi-4 (14B) & DeepSeek R1 Distill (8B):** Selected specifically to test modern "reasoning-first" (thinking) architectures.
    * **Llama 3.1 (8B) & Gemma 2 (9B):** The undisputed industry workhorses for general-purpose, efficient inference.
3. **Engine Compatibility:** Every model selected is natively optimized for `llama.cpp` (`llama-server`), which is what we are using to host the API locally.

## Q2: On what basis are we testing them?

**Answer:**
We are testing them using a custom, automated **100-point heuristic scoring system** (`benchmark.py v4`) designed specifically to measure their ability to accurately extract pure context. The criteria are:

1. **Format Adherence (40 pts):** Can the model successfully output a clean, valid JSON object without wrapping it in markdown or outputting conversational text?
2. **Structural Completeness (30 pts):** Does the output JSON contain all the requested schemas (`app_summary`, `workflows`, and `screen_contexts`)?
3. **Context & Specificity (30 pts):** Does the model realize it is looking at a Reddit client ("RedReader"), and does it explicitly reference the filenames and state numbers from the provided transition graph?
4. **Speed (Informational):** While we track inference speed (in seconds), we do not strictly penalize models for being slower as long as their JSON output is superior in contextual detail. We focus strictly on context extraction, deliberately omitting any deep security risk assessments (like MitM or OAuth leaks).

## Q3: Why did the models fail when taking the whole dataset, and what if we process one level at a time? Do we need to pass the state graph separately each time?

**Answer:**
1. **Why they failed:** The models failed on the full dataset test because of **Context Window Limits** and **VRAM Exhaustion**. Feeding the OCR text for all 200 states simultaneously creates a massive prompt (tens of thousands of tokens). For models in the 8B-14B range, holding that much context requires massive amounts of VRAM, causing their local servers to crash (Connection Refused), timeout (503 Error), or throw Bad Requests.
2. **One level at a time:** If we process the app one level at a time, the prompt size is much smaller, allowing all models to survive easily without crashing.
3. **Passing the State Graph:** Yes, if we process the app level-by-level (in batches), we **MUST** pass the global State Graph separately every single time. This is because the LLM processes each batch completely independently (it has no memory of the previous batches). The State Graph acts as the "map" so the LLM understands how the current level's screens fit into the global app structure.

## Q4: What was the basis for these models to estimate their performance?

**Answer:**
The basis for their performance estimation was our custom **100-point scoring heuristic** inside `benchmark.py`. This script mathematically graded the final output of each model based on:
1. **Format Adherence (40 pts):** Did the model output pure, valid, parsable JSON without breaking the schema or adding markdown?
2. **Structural Completeness (30 pts):** Did the JSON successfully include the three required keys: `app_summary`, `workflows`, and `screen_contexts`?
3. **Context Depth (30 pts):** Did the model correctly identify the app (RedReader) and explicitly reference state numbers/filenames from the graph?
*Qwen 2.5 14B scored 100/100 because it aced all these criteria on the massive full-dataset prompt.*

## Q5: Which temperature are the models performing well at, and why that temperature?

**Answer:**
For this strict JSON context extraction task, the models perform unequivocally best at **Temperature 0.0**.

**Why?** Temperature controls the "randomness" or "creativity" of the LLM. 
* When writing poetry or brainstorming, higher temperatures (0.7) are great. 
* However, when we need a **strict, machine-readable JSON format**, creativity is a liability. At higher temperatures (like 0.3 or 0.7), the models start "hallucinating" extra fields, breaking the JSON schema, or adding conversational text (like "Here is your JSON:") which causes parsing to fail. 
* **Temperature 0.0** makes the model completely deterministic. It forces the model to pick the most logical, highly structured tokens, ensuring it outputs perfectly valid JSON every single time.

## Q6: If we pass one level at a time, how does the model know the whole context flow and which action occurred first?

**Answer:**
This is the magic of our synthesis pipeline! When processing level-by-level to prevent server crashes, the pipeline breaks the work into two phases:
1. **Phase 1 (Batching):** We ask the LLM to generate "mini-reports" for each level purely to describe what is physically on those specific screens.
2. **Phase 2 (Synthesis):** Once all levels are individually described, we take ALL of those mini-reports and pass them *together* in one final prompt along with the **global State Graph**. 

Because the State Graph explicitly defines the exact chronological transitions (e.g., `State 0 -> State 10 -> State 12`), the LLM acts as a detective. It uses the State Graph as a "map" and cross-references it with the mini-reports. The State Graph tells it *when* and *where* an action occurred chronologically, and the mini-reports tell it *what* was on the screen at that moment. This allows it to perfectly piece the full user journey together.

## Q7: Why is the output truncating to just a few states instead of all of them, and how are we going to solve it?

**Answer:**
1. **Why it happens:** When we ask the model to synthesize the final JSON for all 200 screens in a single final prompt, the LLM aggressively summarizes and cuts out 90% of the screens. It does this because if it tried to output the context for all 200 states in a single response, it would hit its hard **maximum output token limit** (typically 4096 tokens) and stop generating midway through, breaking the JSON entirely. To avoid breaking, the LLM "intelligently" summarizes.
2. **How we solve it:** We change the architecture to bypass the LLM's limitation. Instead of relying on the LLM to merge everything in one giant final prompt, we will handle the aggregation in **Python**. We will force the LLM to output a strict JSON array for each small batch of screens (which easily fits within its token limit). Then, our Python script will manually append all those small arrays together into the massive 200-state JSON file!

## Q8: How are we going to do that merging in Python? If we pass all levels at once, isn't it still the same? How does the model know what it built?

**Answer:**
We actually **don't** pass all the levels at once! 

Currently, our Python script loops through the app **level-by-level** (a "batch") and asks the LLM to generate a mini-report for just that batch. Then, at the very end, we pass ALL the mini-reports into ONE final synthesis prompt and ask the LLM to output the final JSON. **That final step is where it breaks**, because the LLM tries to cram 200 screens into a single JSON response and summarizes to save space.

**The Fix:**
1. In the batching loop, instead of asking the LLM for a text "mini-report", we will force it to output a strict JSON array of `screen_contexts` for just those 10-20 screens.
2. Our Python script will take that JSON array and save it into a massive Python list.
3. At the very end, the final synthesis prompt will **only** be asked to generate the overarching `app_summary` and `core_workflows`. We will explicitly tell the LLM: *"Do not generate the screen contexts."*
4. Finally, the Python script mathematically glues the LLM's `core_workflows` together with the massive 200-item Python list we saved in step 2. 

By doing this, the LLM never has to output 200 screens at once, and we guarantee that absolutely zero screens are lost!

## Q9: What is AirLLM, how does it run a 70B model on limited VRAM, and how would we implement it?

**Answer:**
**AirLLM** is an open-source Python library designed to run massive language models (like 70B parameters) on consumer hardware with as little as 4GB-8GB of VRAM. Since your machine has 24GB of VRAM, running a 70B model using AirLLM is completely possible and would leave plenty of headroom!

**How it works (Layer-wise Inference):**
Normally, to run an LLM, your computer must load the *entire* model into your GPU's VRAM at once (which requires 40GB+ for a 70B model). AirLLM uses a technique called **layer-wise inference**. Instead of loading the whole model, it keeps the model on your system RAM (or SSD disk) and only loads **one transformer block/layer into the GPU VRAM at a time**. 
1. It loads Layer 1 into VRAM, computes the math, and discards it.
2. It loads Layer 2 into VRAM, computes the math, and discards it.
*(This keeps the VRAM footprint at around 2-4GB max!)*

**The Trade-off:**
Speed. Because your computer has to constantly shuffle massive amounts of data back and forth between your System RAM/Disk and the GPU for every single word it generates, it is *extremely slow* compared to having the whole model in VRAM. It might generate only 1-2 tokens per second. But for our background benchmark script, if you only care about intelligence and not speed, it's a great option.

**How we would implement it in PyScreen:**
1. We would run `pip install airllm` in your environment.
2. We would add a new backend to our `utils/llm_analyze.py` script.
3. Instead of calling `llama-server` or `Ollama`, we would write a few lines of Python to load the model directly using AirLLM's `AutoModel`:
   ```python
   from airllm import AutoModel
   model = AutoModel.from_pretrained("path/to/your/70B-model")
   ```
4. The Python script would then send our screen contexts directly to this local AirLLM object and generate the final JSON!

## Q10: Are there any other open-source libraries similar to AirLLM that help run massive models on constrained hardware? What are their pros and cons?

**Answer:**
Yes! There are a few major open-source inference engines designed specifically for running massive LLMs on consumer hardware. Here are the top alternatives that could help our PyScreen pipeline, along with their pros and cons:

### 1. llama.cpp / Ollama (Which we are currently using!)
* **How it helps:** Uses **Quantization (GGUF)** and **CPU Offloading**. It shrinks the precision of the model's "brain" from 16-bit to 4-bit, drastically reducing its size. If the model still doesn't fit in your 24GB GPU, it dynamically spills the remaining layers into your System RAM and computes them on your CPU.
* **Pros:** Unmatched flexibility. Runs on almost any hardware (CPU, GPU, Mac). Very fast if the model fits entirely in your 24GB VRAM.
* **Cons:** The 4-bit quantization causes a *slight* loss in reasoning accuracy. If it has to use your CPU for overflow, generation speed drops significantly.

### 2. vLLM (PagedAttention)
* **How it helps:** vLLM doesn't focus on shrinking the model; it focuses on managing the **Context Window Memory (KV Cache)**. When we feed our massive 200-screen JSON context into the model, the GPU memory can bloat and crash. vLLM uses "PagedAttention" (similar to how operating systems manage virtual memory) to virtually eliminate memory waste.
* **Pros:** Massive speedup. It is currently the industry standard for high-throughput batch processing and long-context prompts. It can be up to 24x faster than standard HuggingFace implementations.
* **Cons:** It is strictly for GPU inference. If the model itself (plus context) exceeds your 24GB VRAM, vLLM will simply crash. It does not offload to System RAM.

### 3. ExLlamaV2 (EXL2)
* **How it helps:** An ultra-optimized engine specifically built for consumer GPUs (like your 24GB card). It uses a special quantization format (EXL2) that allows for "variable bitrate" quantization. For example, it can shrink a model to exactly 4.5 bits per weight, allowing you to perfectly maximize your 24GB limit without wasting a single megabyte.
* **Pros:** Faster than `llama.cpp` for pure GPU inference. The variable precision means you get slightly smarter models than standard 4-bit quantization because it utilizes exactly 100% of your VRAM.
* **Cons:** Does not support CPU offloading. If the model goes 1MB over your 24GB limit, it crashes. You also have to specifically find/download `.exl2` formatted models.

### 4. DeepSpeed (ZeRO-Offload)
* **How it helps:** Developed by Microsoft, it allows offloading both model parameters and context to System RAM and NVMe SSDs.
* **Pros:** Can run models well beyond 100B parameters on a single GPU by heavily leveraging your SSD and RAM.
* **Cons:** Extremely complicated to install and configure compared to AirLLM or Ollama. Geared more toward enterprise Linux clusters than personal workstations.

**Summary for our PyScreen Pipeline:**
- If you want to run a **70B model** and don't care about speed: **AirLLM** or **llama.cpp** (with heavy CPU offloading).
- If you want to run a **14B-32B model** as blisteringly fast as possible for batching hundreds of screens: **vLLM** or **ExLlamaV2**.

## Q11: Can we use AirLLM with llama.cpp? What is compatible with llama.cpp? What are some hacks to improve both inference speed and the context we generate?

**Answer:**
### Part 1: AirLLM vs. llama.cpp
No, you **cannot** use AirLLM and `llama.cpp` together. They are two entirely separate, mutually exclusive execution engines that solve the same problem in completely different ways:
* **AirLLM** is built on top of Python (PyTorch/HuggingFace) and uses standard, unquantized models. It saves VRAM by loading one layer at a time.
* **llama.cpp** is a standalone, hardcore C++ engine that uses special `.gguf` quantized models. It saves VRAM by mathematically shrinking the model.

### Part 2: What IS compatible with llama.cpp?
Because `llama.cpp` is a custom backend, you can only use tools designed as "wrappers" around it.
* **Ollama:** This is the most famous one! Ollama is literally just a user-friendly REST API and command-line wrapper built directly on top of `llama.cpp`. 
* **LM Studio / GPT4All:** These are desktop GUI applications that use `llama.cpp` under the hood. 
*(Note: vLLM and ExLlamaV2 are NOT compatible with llama.cpp, they are competing standalone engines).*

### Part 3: Advanced "Hacks" for PyScreen (Inference & Context)
Here are the absolute best hacks we could implement to take this pipeline to the next level:

**Hacks for Inference (Speed & Reliability):**
1. **Prompt Caching (`llama.cpp` feature):** When we process batches, our system prompt is exactly the same every time. `llama.cpp` supports KV Caching. If we enable this, the engine will "remember" the system prompt and completely skip processing those tokens in subsequent batches, massively speeding up generation!
2. **Grammar Constraining (JSON Forcing):** `llama.cpp` allows you to pass a `.gbnf` (Grammar file) to the server. This mathematically *forces* the LLM to only output valid JSON. It intercepts the tokens at the C++ level and literally disables the LLM's ability to output markdown or conversational text, guaranteeing a 0% JSON syntax failure rate.

**Hacks for Context Generation (Intelligence):**
1. **Native Vision Models (VLM):** Right now, we extract OCR text from screens using `easyocr` and send the raw text to the LLM. If we swap to a multimodal model (like `Qwen2-VL` or `Llama-3.2-Vision`), we can skip OCR entirely and feed the raw `.png` images directly to the model. The model will actually *see* the UI (colors, buttons, layout), resulting in insanely accurate context extraction.
2. **RAG (Retrieval-Augmented Generation):** Instead of looping through all 200 screens sequentially, we could generate "vector embeddings" for each screen and store them in a lightweight local Vector Database (like ChromaDB). When synthesizing a workflow, the system would instantly search the database and only pull the 5 screens relevant to that specific user journey.

## Q12: What can we do to improve the output format and pipeline even more?

**Answer:**
Now that our pipeline reliably outputs 100% complete structural JSON instead of conversational markdown, we have unlocked the ability to build a **Visual Dashboard**. Raw massive JSON files are terrible for humans to read, but perfect for computers to parse. 

Here is what we should do to massively improve the project:

1. **Build a Frontend UI (Streamlit or React):** Instead of making users read a raw JSON file, we could build a sleek web dashboard. You upload the `benchmark_results` JSON, and the dashboard automatically draws the State Transition Graph visually using nodes and arrows.
2. **Interactive UI Flows:** When a user clicks on a "Core Workflow" in the dashboard, it could highlight the exact path through the nodes and display the actual `.png` screenshots side-by-side with the LLM's context analysis. This allows researchers to quickly click through the app's journeys.
3. **Bounding Boxes (Future Feature):** Right now, `easyocr` just gives us raw text. If we implemented a true UI parsing model (or a Vision-Language Model), the JSON could include the `[x, y]` coordinates of buttons. The dashboard could then physically draw red boxes around the buttons the user needs to press for a given workflow!

## Q13: What is the exact workflow of PyScreen? What is happening under the hood in detail?

**Answer:**
Here is the exact step-by-step process of what happens under the hood when we run `benchmark.py` on your machine:

**Step 1: Text Extraction (OCR) — `utils/text_compute.py`**
*   The script scans the `ARES_screenshots` directory and finds all 28 `.png` images.
*   It feeds every single image into `easyocr`, an Optical Character Recognition tool, which scans the pixels and extracts every single word of text visible on the screen.
*   To save time on future runs, it saves all this text into `benchmark_results/ocr_cache.json`.

**Step 2: State Graph Parsing — `benchmark.py`**
*   The script reads `ARES_state_graph.txt`.
*   This file is a "map" that tells the script the chronological order of the screens (e.g., `State 0 -> State 10`). The script groups these paths into distinct "levels" (user journeys).

**Step 3: Batch Analysis — `utils/llm_analyze.py`**
*   The script loops through the app level-by-level (batching).
*   For each level, it bundles the OCR text for those specific screens and sends it to our local LLM (Qwen 2.5 running on `llama-server`).
*   The LLM reads the OCR text and generates a strict JSON array of `screen_contexts` (describing what each screen physically is).

**Step 4: Python Aggregation (Our Custom Fix)**
*   As the LLM returns the JSON for each batch, our Python script intercepts it.
*   It physically rips the `screen_contexts` out of the LLM's response and securely saves them into a massive list in your computer's system RAM.

**Step 5: Final Synthesis (Workflows)**
*   Once all the batches are finished, the script sends the State Graph and the aggregated screen contexts to the LLM one last time.
*   We explicitly instruct the LLM: *"Read these contexts and extract every single unique workflow path in high detail, but do NOT output the contexts themselves."*
*   The LLM generates the `app_summary` and the 10 detailed `core_workflows`.

**Step 6: Final JSON Assembly**
*   Finally, the Python script mathematically glues the LLM's workflows together with our massive list of screen contexts. 
*   It outputs the perfect, 100% complete `t0.0_report.json` file!

## Q14: Why can't we use 70B and 30B models after quantizing them?

**Answer:**
We actually **CAN** use a 30B model! 

Here is the quick math for how much memory an LLM needs. When you quantize a model to 4-bit (which is the standard `Q4_K_M` we are using), it takes roughly **0.6 GB to 0.7 GB of VRAM per 1 Billion parameters**.

Since your machine has **24 GB of VRAM**, here is how the models fit:

**1. The 30B / 32B Models (Perfect Fit!)**
*   **Math:** 32B parameters * 0.65 GB = **~20.8 GB of VRAM**.
*   **Can we run it?** **YES!** It fits entirely inside your 24GB GPU. You will even have about 3GB left over for the "Context Window" (the memory needed to hold all the OCR text we send it). Models like *Qwen2.5-32B* or *Llama-3-70B (Wait no, Llama is 70B)* or *Command-R 35B* are fantastic choices for your machine!

**2. The 70B Models (The Spillover Problem)**
*   **Math:** 70B parameters * 0.65 GB = **~45 GB of VRAM**.
*   **Can we run it?** **Yes, but with a catch.** Because it requires 45GB and you only have 24GB, `llama.cpp` will load half the model into your GPU, and it will physically be forced to "spill" the remaining 21GB into your System RAM. 
*   **The result:** It will run, but because the CPU has to handle 50% of the workload, the generation speed will plummet. It might take 30-60 seconds just to read our massive JSON prompt. If you don't care about speed, it works beautifully. 

*(Note: You could theoretically quantize a 70B model down to 2-bit so it fits entirely in 24GB, but shrinking a model's brain that aggressively causes "brain damage" and makes it hallucinate constantly.)*

## Q15: What about the new Kimi K3 model? What are its parameters and can we use it locally?

**Answer:**
Moonshot AI recently announced **Kimi K3**, and its specs are absolutely mind-blowing! It is an Autoregressive Mixture-of-Experts (MoE) model.

*   **Total Parameters:** 2.8 Trillion
*   **Active Parameters:** ~50 Billion active parameters per token
*   **Release Date:** They have announced it will be open-weights, but the official HuggingFace repository isn't dropping until **July 27, 2026**.

**Can we run it on your machine?**
Unfortunately, **No.**
Even if we wait for the open-source weights to drop next week, a 2.8 Trillion parameter model is far too massive for any consumer PC on Earth. If we quantized it down to 4-bit, it would still require roughly **1,800 GB (1.8 Terabytes) of RAM** just to load it into memory! 

Since your machine has 128 GB of RAM and 24 GB of VRAM, the largest models you can feasibly run are around the 100B to 140B range (like Command-R Plus or WizardLM-8x22B). 

If you want to use Kimi K3 for PyScreen, we would have to skip running it locally via `llama.cpp` and instead rewrite our python script to make API calls directly to Moonshot's official servers over the internet!

## Q16: Why are the 70B models not good for our task?

**Answer:**
In theory, a 70B model is brilliant, but for this specific local hardware setup and context extraction task, they fail for three reasons:
1. **Memory & Speed Bottlenecks:** Your machine has 24GB of VRAM and 128GB of System RAM. A 70B model requires about 45GB. This means 21GB spills over into your System RAM (CPU). CPU inference is exponentially slower than GPU inference. As we saw with Qwen 72B, it generated tokens so slowly that the API requests completely timed out after 10 minutes per screen.
2. **Instruction Forgetting:** Massive models like Llama 3.1 70B are heavily trained to be conversational assistants. When given a massive wall of OCR text and asked to output strict JSON, they often "forget" the formatting constraint and write a beautiful (but unparseable) Markdown essay instead, breaking the pipeline.
3. **The "Sweet Spot" Phenomenon:** 14B models (like Qwen 2.5 14B) fit *entirely* inside your 24GB VRAM. This means they run at blazing-fast GPU speeds. Furthermore, Qwen 2.5 14B is specifically tuned for coding and structured data, making it far superior at strict JSON generation than a conversational 70B model.

## Q17: Is the pipeline finished, and how can we reduce LLM hallucination and improve context quality further?

**Answer:**
Yes, the core aggregation pipeline is fundamentally complete! We successfully replaced the old, lossy LLM summarization with a Python-native aggregation strategy that losslessly stitches every single state together. We also identified the optimal engine (Qwen2.5-14B at Temp 0.0) which generates massive 20,000+ character reports without truncating workflows.

Since this is a backend data pipeline, here are the best ways to scientifically reduce hallucination and improve context quality going forward:

1. **JSON Grammar Enforcement (GBNF):**
   *   **What:** We can pass a strict `.gbnf` (Grammar) schema file to `llama-server`.
   *   **Why:** This mathematically restricts the LLM from outputting any token that doesn't fit the exact JSON schema. It is a bulletproof way to guarantee the model never hallucinates keys, forgets brackets, or outputs free-text markdown, achieving 100% JSON compliance.
2. **Few-Shot Prompting (Golden Examples):**
   *   **What:** We inject 1 or 2 perfect "Golden Examples" of an OCR input and its ideal JSON output directly into the system prompt.
   *   **Why:** LLMs learn exceptionally well "in-context." By showing it exactly what a perfect extraction looks like, we drastically reduce hallucinations where the model invents buttons that don't exist in the OCR.
3. **Self-Correction / Verification Loop:**
   *   **What:** We add a quick, secondary LLM pass (using a fast model like Phi-4 or Qwen 14B) that acts as an "Auditor."
   *   **Why:** The Auditor model reads the generated context and compares it to the original OCR, specifically looking for hallucinations (e.g., "Did the first model invent a 'Submit' button that isn't in the OCR?"). If it finds one, it scrubs it from the context.
4. **Confidence Scoring:**
   *   **What:** We add a `"confidence_score": (0-100)` field to the JSON schema.
   *   **Why:** The LLM self-evaluates how messy the OCR was. If a screen has a confidence score of 30%, the pipeline knows to flag that specific state for manual review or secondary processing, rather than blindly trusting hallucinated context.

---
*(Future questions will be appended below)*

## Q18: Doesn't upscaling lead to errors or repeating text? What exactly are we upscaling?

**Answer:**
We are upscaling the **image resolution (DPI)**, not the text itself. 

When we use OpenCV to upscale (`cv2.resize` with `fx=2, fy=2`), we are simply making the image twice as large in pixels (e.g., turning a 1080x1920 screenshot into a 2160x3840 image). We are **not** copying, duplicating, or repeating the text strings. 

**Why do we do this?**
Tesseract was originally designed in the 1990s to read high-quality scanned paper documents (typically 300 DPI). Modern mobile screenshots, however, are often 72 to 144 DPI. At that low resolution, tiny mobile fonts (like a small "Accept" button) look like blurry, pixelated blobs to Tesseract, causing it to fail or guess incorrectly. 

By upscaling the image using "Bicubic Interpolation", OpenCV smoothly fills in the extra pixels, making the blurry edges of the letters much sharper. When Tesseract reads this larger, sharper image, it correctly recognizes the small letters without hallucinating or repeating anything!

## Q19: We have a GPU — aren't we using it? Why was the server so slow?

**Answer:**
Yes, we are absolutely using the GPU! The `llama-server` offloads the entire Qwen 2.5 32B model into the 24GB GPU VRAM, and all the actual matrix math (token generation) runs on the GPU at ~43 tokens/second.

The confusion arose during the 1000-state benchmark when we saw the server running at only **0.8 tokens/second**. What happened was a **VRAM overflow**: the pipeline was configured to send 3 batches concurrently using `ThreadPoolExecutor(max_workers=3)`. This caused `llama-server` to allocate 3 parallel KV cache slots (108,000 tokens total), which overflowed the 24GB VRAM and forced the GPU to spill into system RAM. When this happens, the math that normally runs at GPU speed (~43 tok/s) gets offloaded to the CPU, which is exponentially slower (~0.8 tok/s).

**The Fix:** We forced strictly sequential processing (`max_workers=1`), ensuring only 1 KV cache slot is allocated at a time. This keeps everything inside the GPU VRAM, and we went back to blazing-fast GPU speeds.

## Q20: Why test with a smaller model if we're running locally? It doesn't matter as long as it fits in VRAM, right?

**Answer:**
You're absolutely right that running locally eliminates the per-token cost advantage of smaller models (unlike cloud APIs where smaller = cheaper). However, there are real, measurable advantages to testing smaller models:

1. **Speed:** A 14B model generates tokens ~1.5x faster than 32B (64.8 vs 43 tok/s). This turned a 2.7-hour LLM phase into just 20 minutes. For a 1000-state benchmark, that's a massive time saving.

2. **VRAM Headroom:** A 14B model (8.4 GB) leaves ~15 GB of VRAM free for the KV cache, allowing larger context windows or even concurrent batch processing without OOM crashes. The 32B model (19 GB) leaves only ~5 GB, making it fragile.

3. **Comparative Analysis:** Your incharge likely wants a **speed vs. accuracy tradeoff chart** to justify the model choice in reports or papers. Showing that the 14B model is both faster AND more accurate makes a compelling case.

4. **Task-Specific Fit:** Larger models aren't always better. The 32B model has more general knowledge, but the 14B variant is specifically optimized for instruction-following and structured JSON output, which is exactly what our pipeline demands.

## Q21: By analyzing the LLM output across all models, which is the best ≤14B model and why? How does it compare to the 32B?

**Answer:**

### Best ≤14B Model: **Qwen 2.5 14B** 🏆

After deep-diving into the actual JSON output quality across 9 sampled screens and running full statistical analysis across all 1000 states, Qwen 2.5 14B dominates every quality metric:

| Metric | Qwen 14B | Mistral 12B | Gemma 9B | LLaMA 8B |
|---|---|---|---|---|
| Avg Confidence | **81.9** | 72.8 | 68.9 | 68.4 |
| High Confidence (≥80) | **88%** | 68% | 33% | 63% |
| Flagged as Unreliable | **1.6%** | 16.4% | 7.2% | 22.0% |
| State Coverage | 1000/1000 ✅ | 1000/1000 ✅ | 985/1000 ❌ | 1120/1000 ❌ |
| Verification Notes | **45** | 274 | 162 | 119 |

**Why each model fell short:**
- **Mistral Nemo 12B:** Verbose but over-hallucinated. The verifier flagged 16.4% of screens with 274 verification notes.
- **Gemma 2 9B:** Too conservative. Missed 15 screens entirely and only 33% of outputs scored ≥80 confidence.
- **LLaMA 3.1 8B:** Fastest (114.8 tok/s) but worst quality. Hallucinated 120 extra entries, 22% flagged, and consistently misspelled "Reddit" as "Redalit" or "Redelit."

### Qwen 14B vs Qwen 32B:

Surprisingly, the 14B **outperforms** the 32B:

| Metric | Qwen 32B | Qwen 14B | Winner |
|---|---|---|---|
| Avg Confidence | 78.6 | **81.9** | 14B |
| High Confidence (≥80) | 65% | **88%** | 14B |
| Flagged (<50) | 2.8% | **1.6%** | 14B |
| LLM Time (1000 states) | 9,980s (2.7h) | **1,244s (20m)** | 14B |
| Tokens/sec | 43 | **64.8** | 14B |
| Output Size | 303K chars | **309K chars** | 14B |

The 32B's only marginal advantage is slightly more precise type labels on a handful of screens (e.g., "Subreddit List" vs "Front Page"), but the 14B consistently produces richer, more detailed context descriptions with dramatically fewer errors. 

**Conclusion:** For this specific pipeline (strict JSON extraction from OCR text), Qwen 2.5 14B is objectively the superior choice — higher quality, lower error rate, 8x faster, and half the VRAM usage.

---
*(Future questions will be appended below)*

