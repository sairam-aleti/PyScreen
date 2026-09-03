import os
import shutil
import random

source_dir = "ARES_screenshots"
target_dir = "ARES_1000_screenshots"
graph_file = "ARES_1000_state_graph.txt"

# Recursively get source screenshots
src_images = []
for root, _, files in os.walk(source_dir):
    for f in files:
        if f.endswith('.png'):
            src_images.append(os.path.join(root, f))

if not src_images:
    print("Error: No source images found in", source_dir)
    exit(1)

# Create target directory
if os.path.exists(target_dir):
    shutil.rmtree(target_dir)
os.makedirs(target_dir)

print(f"Copying {len(src_images)} source images to simulate 1000 states...")

# Generate 1000 physical images (by repeating the source images)
for i in range(1000):
    src_file = src_images[i % len(src_images)]
    dest_file = f"state_{i}.png"
    # Copy instead of symlink to ensure cross-platform / real file read simulation
    shutil.copy(src_file, os.path.join(target_dir, dest_file))

print(f"Successfully generated 1000 screenshots in {target_dir}")

# Generate State Graph (sequential with some random branches)
print(f"Generating synthetic 1000-node state graph...")
with open(graph_file, "w") as f:
    for i in range(999):
        # 90% chance it just goes to the next state sequentially
        # 10% chance it branches to a random future state
        if random.random() < 0.9:
            f.write(f"State {i} -> State {i+1}\n")
        else:
            branch_target = min(i + random.randint(2, 10), 999)
            f.write(f"State {i} -> State {branch_target}\n")
            # also connect to the next state so we don't break the chain entirely
            f.write(f"State {i} -> State {i+1}\n")

print(f"Successfully generated {graph_file}")
