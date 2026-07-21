import os
from huggingface_hub import hf_hub_download, HfFileSystem
import shutil

repo_id = "bartowski/Meta-Llama-3.1-70B-Instruct-GGUF"
DOWNLOAD_DIR = "/home/apf/Documents/models/large_models"

print("Downloading Llama-3.1-70B-Instruct-Q4_K_M.gguf...")
hf_hub_download(
    repo_id=repo_id,
    filename="Meta-Llama-3.1-70B-Instruct-Q4_K_M.gguf",
    local_dir=DOWNLOAD_DIR,
    local_dir_use_symlinks=False
)
print("Finished!")
