from PIL import Image, features
import io
import logging

# Configure logging once
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def is_format_supported(format_name: str) -> bool:
    """Check if a format like 'avif' or 'webp' is supported by current Pillow build."""
    # Ensure the format name is in lowercase for the check
    return features.check(format_name.lower())

def crop_image_to_aspect_ratio(
    image: Image.Image,
    horizontal_target_aspect_ratio: str = "16:9",
    vertical_target_aspect_ratio: str = "9:16"
) -> Image.Image: # Added return type hint for clarity
    """
    Crops an image to a target aspect ratio, prioritizing the orientation
    (horizontal or vertical) closest to the original image.
    If a valid crop cannot be made, the original image is returned.
    """
    width, height = image.size
    logger.debug(f"Original image size: {width}x{height}")

    # Determine which target aspect ratio to use based on image orientation
    if width >= height:
        logger.debug("Original image is horizontal or square. Using horizontal target ratio.")
        current_target_aspect_ratio_str = horizontal_target_aspect_ratio
    else:
        logger.debug("Original image is vertical. Using vertical target ratio.")
        current_target_aspect_ratio_str = vertical_target_aspect_ratio

    try:
        ratio_w, ratio_h = map(int, current_target_aspect_ratio_str.split(':'))
        if ratio_h == 0:
            raise ValueError("Target aspect ratio height cannot be zero.")
        current_target_ratio = ratio_w / ratio_h
    except ValueError as e:
        logger.error(f"Invalid aspect ratio format or value: '{current_target_aspect_ratio_str}'. Error: {e}")
        raise ValueError("Invalid aspect ratio format or value provided.") from e

    # Calculate new dimensions for cropping
    # The logic here seems to incorrectly apply min for new_width/height based on comparison to required_width/height.
    # It should correctly calculate the size of the crop box based on which dimension is limiting.

    if width / height > current_target_ratio: # Original is wider than target, so height is limiting
        new_height = height
        new_width = int(height * current_target_ratio)
        if new_width > width: # Should not happen if logic is correct, but as a safeguard
             logger.warning(f"Calculated new_width ({new_width}) exceeds original width ({width}). Adjusting.")
             new_width = width
             new_height = int(width / current_target_ratio)
             if new_height > height: # If even after adjusting, height exceeds, something is very wrong or ratio is extreme
                 logger.error(f"Cannot achieve target ratio {current_target_aspect_ratio_str} without upscaling one dimension. Returning original image.")
                 return image

    else: # Original is taller or exactly the target ratio, so width is limiting
        new_width = width
        new_height = int(width / current_target_ratio)
        if new_height > height: # Should not happen if logic is correct, but as a safeguard
            logger.warning(f"Calculated new_height ({new_height}) exceeds original height ({height}). Adjusting.")
            new_height = height
            new_width = int(height * current_target_ratio)
            if new_width > width: # If even after adjusting, width exceeds, something is very wrong or ratio is extreme
                logger.error(f"Cannot achieve target ratio {current_target_aspect_ratio_str} without upscaling one dimension. Returning original image.")
                return image

    # Calculate crop coordinates to center the crop
    left = (width - new_width) // 2
    top = (height - new_height) // 2
    right = left + new_width
    bottom = top + new_height

    # Validate crop box dimensions before cropping
    if right <= left or bottom <= top or left < 0 or top < 0 or right > width or bottom > height:
        logger.error(f"Calculated invalid crop box: ({left}, {top}, {right}, {bottom}). Original image: {width}x{height}. New size: {new_width}x{new_height}. Returning original image.")
        return image

    cropped = image.crop((left, top, right, bottom))
    logger.debug(f"Cropped image size: {cropped.size[0]}x{cropped.size[1]} from original {width}x{height} with ratio {current_target_aspect_ratio_str}")
    return cropped


def convert_to_webp(image: Image.Image, quality: int = 75) -> io.BytesIO:
    """Convert to WebP format in memory."""
    byte_arr = io.BytesIO()
    try:
        if not is_format_supported("webp"):
            # It's generally better to raise a specific error that callers can catch
            # or handle, rather than just logging and raising a generic RuntimeError.
            # However, for consistency with your AVIF function, I'll keep RuntimeError.
            raise RuntimeError("WebP not supported in this Pillow build. Please ensure libwebp is installed and Pillow is built with WebP support.")
        image.save(byte_arr, format='WEBP', optimize=True, quality=quality)
        byte_arr.seek(0)
        logger.debug("Image converted to WebP.")
        return byte_arr
    except Exception as e:
        logger.error(f"Failed to convert image to WebP: {e}")
        # Re-raise the exception to allow the calling code to handle it
        raise
