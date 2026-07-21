import os
from huggingface_hub import hf_hub_download, HfFileSystem
import shutil

MODELS = {
    "Llama-3.3-70B-Instruct": "bartowski/Llama-3.3-70B-Instruct-GGUF",
    "Qwen2.5-72B-Instruct": "Qwen/Qwen2.5-72B-Instruct-GGUF",
    "DeepSeek-R1-Distill-Llama-70B": "unsloth/DeepSeek-R1-Distill-Llama-70B-GGUF",
    "Mixtral-8x7B-Instruct-v0.1": "TheBloke/Mixtral-8x7B-Instruct-v0.1-GGUF"
}

DOWNLOAD_DIR = "/home/apf/Documents/models/large_models"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

fs = HfFileSystem()

for model_name, repo_id in MODELS.items():
    print(f"=====================================")
    print(f"Downloading {model_name}...")
    
    # Find files matching Q4_K_M in the repo
    # Usually they end with .gguf or have multiple splits
    files = fs.ls(repo_id)
    target_files = []
    
    for f in files:
        fname = os.path.basename(f["name"])
        # DeepSeek and Mixtral usually have Q4_K_M in the name
        # We also need to handle q4_k_m (lowercase)
        if ("Q4_K_M" in fname or "q4_k_m" in fname) and fname.endswith(".gguf"):
            target_files.append(fname)
            
    if not target_files:
        print(f"Could not find Q4_K_M files for {model_name} in {repo_id}")
        continue
        
    for fname in target_files:
        print(f"  -> Downloading {fname}...")
        hf_hub_download(
            repo_id=repo_id,
            filename=fname,
            local_dir=DOWNLOAD_DIR,
            local_dir_use_symlinks=False
        )
        
print("All large models successfully downloaded!")
