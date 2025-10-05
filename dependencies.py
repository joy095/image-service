import os
import logging

# ⚠️ MUST be set BEFORE importing NudeDetector / ONNX
os.environ["ONNX_DISABLE_CPUINFO"] = "1"

from nudenet import NudeDetector
from config import settings  # your settings.py

logger = logging.getLogger(__name__)

def initialize_nudenet_detector():
    """Initializes the NudeNet detector instance safely in sandbox."""
    model_path = settings.MODEL_PATH
    if not os.path.exists(model_path):
        logger.warning(f"NudeNet model not found at {model_path}. Nudity detection skipped.")
        return None
    try:
        detector = NudeDetector(
            model_path=model_path,
            inference_resolution=640,
            providers=["CPUExecutionProvider"]  # Force CPU-only
        )
        logger.info("NudeNet detector initialized successfully.")
        return detector
    except Exception as e:
        logger.error(f"Failed to initialize NudeNet detector: {e}")
        return None

# Initialize detector once at startup
detector = initialize_nudenet_detector()

def get_detector():
    """Dependency function to get the detector instance."""
    return detector

# Adult content labels
ADULT_CONTENT_LABELS = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_BREAST_AREOLA",
    "FEMALE_GENITALIA", "MALE_GENITALIA"
]
