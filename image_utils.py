from PIL import Image
import io
import logging
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def crop_image_to_aspect_ratio(image: Image.Image, target_aspect_ratio: float = settings.CROPPED_ASPECT_RATIO):
    """
    Crops an image to the target aspect ratio, centering the crop.
    """
    original_width, original_height = image.size
    original_aspect_ratio = original_width / original_height

    if abs(original_aspect_ratio - target_aspect_ratio) < 0.01: # Check if already close
        logger.info("Image aspect ratio is close to target, no cropping needed.")
        return image

    if original_aspect_ratio > target_aspect_ratio:
        # Original is wider than target, crop width
        new_width = int(original_height * target_aspect_ratio)
        left = (original_width - new_width) // 2
        top = 0
        right = left + new_width
        bottom = original_height
        logger.info(f"Cropping width: ({left}, {top}, {right}, {bottom})")
        return image.crop((left, top, right, bottom))
    else:
        # Original is taller or equal to target, crop height
        new_height = int(original_width / target_aspect_ratio)
        left = 0
        top = (original_height - new_height) // 2
        right = original_width
        bottom = top + new_height
        logger.info(f"Cropping height: ({left}, {top}, {right}, {bottom})")
        return image.crop((left, top, right, bottom))

def convert_to_webp(image: Image.Image):
    """Converts a PIL Image object to WebP format in a BytesIO object."""
    byte_arr = io.BytesIO()
    try:
        image.save(byte_arr, format='WEBP')
        byte_arr.seek(0) # Rewind to the beginning of the stream
        logger.info("Image converted to WebP.")
        return byte_arr
    except Exception as e:
        logger.error(f"Failed to convert image to WebP: {e}")
        raise