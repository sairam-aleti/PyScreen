"""
Frame loading utilities for PyScreen.
Supports loading from screenshot directories and extracting frames from video files.
"""
import cv2
import os
import json
import logging

logger = logging.getLogger("pyscreen")


def get_frames_from_dir(input_dir):
    """
    Load all screenshots from a directory in alphanumeric order.
    Only loads files with purely numeric basenames (e.g., 0000.jpg, 0001.png).

    Args:
        input_dir: Path to directory containing numbered screenshot files.

    Returns:
        List of tuples: (filename, frame).

    Raises:
        FileNotFoundError: If the directory doesn't exist.
        ValueError: If the directory contains no valid screenshots.
    """
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Screenshot directory not found: {input_dir}")

    all_frames = []

    try:
        files = sorted(os.listdir(input_dir))
    except PermissionError as e:
        raise PermissionError(f"Cannot read directory '{input_dir}': {e}")

    image_files = [
        f for f in files
        if f.lower().endswith(('.png', '.jpg', '.jpeg'))
        and os.path.splitext(f)[0].isdigit()
    ]

    if len(image_files) == 0:
        raise ValueError(
            f"No numbered screenshots found in '{input_dir}'. "
            f"Files must be named with numbers (e.g., 0000.jpg, 0001.png)."
        )

    logger.info(f"Found {len(image_files)} screenshots in {input_dir}")

    skipped = 0
    for filename in image_files:
        filepath = os.path.join(input_dir, filename)
        frame = cv2.imread(filepath)

        if frame is not None:
            all_frames.append((filename, frame))
            logger.debug(f"  Loaded: {filename}")
        else:
            skipped += 1
            logger.warning(f"  Corrupt or unreadable file: {filename}, skipping.")

    if skipped > 0:
        logger.warning(f"  Skipped {skipped} corrupt file(s).")

    if len(all_frames) == 0:
        raise ValueError(f"All {len(image_files)} files in '{input_dir}' were unreadable.")

    logger.info(f"Successfully loaded {len(all_frames)} screenshots.")
    return all_frames


def get_frames_from_video(video_path, sample_rate=1.0):
    """
    Extract frames from a video file at a given sample rate.

    Args:
        video_path: Path to the video file (.mov, .mp4, .avi, etc.)
        sample_rate: Frames to extract per second of video. Default 1.0 = 1 frame/sec.
                     Use 0 to extract ALL frames (not recommended for long videos).

    Returns:
        List of tuples: (filename, frame) where filename is like "frame_0001.jpg"

    Raises:
        FileNotFoundError: If the video file doesn't exist.
        ValueError: If the file is not a valid video.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(
            f"Cannot open video file: {video_path}. "
            f"File may be corrupt or in an unsupported format."
        )

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    logger.info(f"Video: {os.path.basename(video_path)}")
    logger.info(f"  FPS: {fps:.1f}, Total frames: {total_frames}, Duration: {duration:.1f}s")

    if fps <= 0 or total_frames <= 0:
        cap.release()
        raise ValueError(f"Invalid video metadata: FPS={fps}, frames={total_frames}")

    # Calculate which frames to extract
    if sample_rate <= 0:
        # Extract all frames
        frame_interval = 1
    else:
        frame_interval = max(1, int(fps / sample_rate))

    logger.info(f"  Extracting 1 frame every {frame_interval} frames (sample_rate={sample_rate}/s)")

    all_frames = []
    frame_index = 0
    extracted_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_index % frame_interval == 0:
            extracted_count += 1
            filename = f"frame_{extracted_count:04d}.jpg"
            all_frames.append((filename, frame))
            logger.debug(f"  Extracted: {filename} (source frame {frame_index})")

        frame_index += 1

    cap.release()

    if len(all_frames) == 0:
        raise ValueError(f"No frames could be extracted from video: {video_path}")

    logger.info(f"Extracted {len(all_frames)} frames from video.")
    return all_frames


def get_frames_from_ares_dir(input_dir):
    """
    Load frames from an ARES screenshot directory structure.
    Parses state_graph.json and loads level_X/state_X.png files.
    
    Args:
        input_dir: Path to the ARES directory.

    Returns:
        Tuple of (all_frames, state_graph)
        - all_frames: List of (filename, frame) tuples
        - state_graph: Parsed dictionary from state_graph.json
    """
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"ARES directory not found: {input_dir}")

    # Parse state_graph.json
    state_graph_path = os.path.join(input_dir, "state_graph.json")
    if not os.path.isfile(state_graph_path):
        raise FileNotFoundError(f"state_graph.json not found in {input_dir}")

    with open(state_graph_path, "r", encoding="utf-8") as f:
        state_graph = json.load(f)

    logger.info(f"Loaded state_graph.json with {len(state_graph)} states.")

    all_frames = []
    skipped = 0
    
    # Map state ID to image path by walking the directory
    found_states = {}
    for root, _, files in os.walk(input_dir):
        for file in files:
            name, ext = os.path.splitext(file)
            if ext.lower() in ['.png', '.jpg', '.jpeg'] and name.startswith('state_'):
                try:
                    state_id = int(name.split('_')[1])
                    found_states[state_id] = os.path.join(root, file)
                except ValueError:
                    pass # ignore files like state_abc.png

    # Iterate through expected states based on the graph keys
    num_states = len(state_graph)
    
    for i in range(num_states):
        if str(i) not in state_graph and i not in state_graph:
            # Maybe the graph is sparse, but let's try to load it if we found an image
            pass

        if i in found_states:
            image_path = found_states[i]
            frame = cv2.imread(image_path)
            level_name = os.path.basename(os.path.dirname(image_path))
            filename = f"{level_name}/state_{i}.png" # embed level name for batching
            
            if frame is not None:
                all_frames.append((filename, frame))
                logger.debug(f"  Loaded: {filename}")
            else:
                skipped += 1
                logger.warning(f"  Corrupt or unreadable file: {image_path}, skipping.")
        else:
            logger.warning(f"  Missing image file for state {i}")
            skipped += 1

    if skipped > 0:
        logger.warning(f"  Skipped {skipped} missing or corrupt states.")

    if len(all_frames) == 0:
        raise ValueError(f"No frames could be loaded from ARES directory '{input_dir}'.")

    logger.info(f"Successfully loaded {len(all_frames)} states.")
    return all_frames, state_graph
