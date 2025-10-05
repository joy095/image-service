# dependencies.py
import os
import logging
from nudenet import NudeDetector
from config import settings # Assuming you have a config.py with settings

logger = logging.getLogger(__name__)

def initialize_nudenet_detector():
    """Initializes the NudeNet detector instance."""
    model_path = settings.MODEL_PATH
    if not os.path.exists(model_path):
        logger.warning(f"NudeNet model file not found at {model_path}. Nudity detection will be skipped.")
        return None
    try:
        detector = NudeDetector(model_path=model_path, inference_resolution=640)
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

# List of labels considered as adult content
ADULT_CONTENT_LABELS = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_BREAST_AREOLA",
    "FEMALE_GENITALIA", "MALE_GENITALIA"
]