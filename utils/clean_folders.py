"""
Utility to clean/prepare the output folder.
"""
import os
import shutil
import logging

logger = logging.getLogger("pyscreen")


def clean_folders(output_dir="result"):
    """
    Prepare the output directory. Creates it if it doesn't exist,
    clears existing files if it does.

    Args:
        output_dir: Path to the output directory. Default: "result"
    """
    if os.path.exists(output_dir):
        files = os.listdir(output_dir)
        for f in files:
            filepath = os.path.join(output_dir, f)
            try:
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    logger.debug(f"  Removed: {filepath}")
            except Exception as e:
                logger.warning(f"  Could not remove {filepath}: {e}")
    else:
        os.makedirs(output_dir)
        logger.debug(f"  Created output directory: {output_dir}")

    return True