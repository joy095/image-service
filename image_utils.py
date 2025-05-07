from PIL import Image
import io
import logging
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def crop_image_to_square(image: Image.Image, target_size: int = 512):
    """
    Crops the center of the image to a square, then resizes it to target_size x target_size.
    """
    width, height = image.size
    min_side = min(width, height)

    # Calculate coordinates to center crop the square
    left = (width - min_side) // 2
    top = (height - min_side) // 2
    right = left + min_side
    bottom = top + min_side

    logger.info(f"Cropping square: ({left}, {top}, {right}, {bottom})")
    cropped = image.crop((left, top, right, bottom))

    # Resize to desired size (e.g., 512x512)
    resized = cropped.resize((target_size, target_size), Image.LANCZOS)
    logger.info(f"Resized cropped image to {target_size}x{target_size}")
    return resized


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