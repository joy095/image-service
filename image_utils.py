from PIL import Image
import io
import logging
# Assuming config.settings exists and is configured
# from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def crop_image_to_aspect_ratio(
    image: Image.Image,
    horizontal_target_aspect_ratio: str = "16:9",
    vertical_target_aspect_ratio: str = "9:16" # Added parameter for vertical images
):
    
    width, height = image.size
    logger.debug(f"Original image size: {width}x{height}")

    # Determine which target aspect ratio to use based on orientation
    if width >= height: # Original image is horizontal or square
        logger.debug("Original image is horizontal or square. Using horizontal target ratio.")
        current_target_aspect_ratio_str = horizontal_target_aspect_ratio
    else: # Original image is vertical (height > width)
        logger.debug("Original image is vertical. Using vertical target ratio.")
        current_target_aspect_ratio_str = vertical_target_aspect_ratio

    # Parse the chosen target aspect ratio
    try:
        ratio_w, ratio_h = map(int, current_target_aspect_ratio_str.split(':'))
        if ratio_h == 0:
             raise ValueError("Target aspect ratio height cannot be zero.")
        current_target_ratio = ratio_w / ratio_h
    except ValueError as e:
        logger.error(f"Invalid aspect ratio format or value: {current_target_aspect_ratio_str}. Expected format like '16:9'. Error: {e}")
        raise ValueError("Invalid aspect ratio format or value") from e # Chain the exception

    new_width, new_height = width, height # Initialize with original dimensions

    if width >= height: # Original image is horizontal or square
        logger.debug(f"Applying horizontal crop rule for target ratio {current_target_aspect_ratio_str}.")
        # Rule: Crop horizontally (keep original height, reduce width)
        new_height = height
        # Calculate the width needed to achieve the target ratio with the original height
        required_width_for_target = int(height * current_target_ratio)

      
        new_width = min(width, required_width_for_target)

        if required_width_for_target > width:
             logger.warning(f"Target ratio {current_target_aspect_ratio_str} ({current_target_ratio:.2f}) is wider than or same as original ratio ({width/height:.2f}).")
             logger.warning("Cannot achieve target ratio by only cropping width. Resulting ratio will be original ratio.")
             # new_width is already set to min(width, required_width_for_target) which is 'width' in this case.

        logger.debug(f"Calculated dimensions for horizontal crop: {new_width}x{new_height}")

    else: # Original image is vertical (height > width)
        logger.debug(f"Applying vertical crop rule for target ratio {current_target_aspect_ratio_str}.")
        # Rule: Crop vertically (keep original width, reduce height)
        new_width = width

        target_h = int(width / current_target_ratio)

      
        new_height = min(height, target_h) # Corrected logic for vertical crop

        if target_h > height:
             logger.warning(f"Target ratio {current_target_aspect_ratio_str} ({current_target_ratio:.2f}) is more vertical than original ratio ({width/height:.2f}).")
             logger.warning("Cannot achieve target ratio by only cropping height. Resulting ratio will be based on original width and capped height.")
             # new_height is already set to min(height, target_h) which is 'height' in this case.

        logger.debug(f"Calculated dimensions for vertical crop: {new_width}x{new_height}")


    
    left = (width - new_width) // 2
    top = (height - new_height) // 2
    
    right = left + new_width
    bottom = top + new_height

    # Ensure coordinates are within bounds (good practice)
    left = max(0, left)
    top = max(0, top)
    right = min(width, right) # Ensure right boundary doesn't exceed image width
    bottom = min(height, bottom) # Ensure bottom boundary doesn't exceed image height


    logger.debug(f"Cropping box: ({left}, {top}, {right}, {bottom})")

    # Check if the calculated crop box is valid (has positive dimensions)
    if right <= left or bottom <= top:
         logger.error("Calculated crop box is invalid.")

         return image # Return original image in case of invalid crop box calculation

    cropped = image.crop((left, top, right, bottom))

    logger.debug(f"Cropped image size: {cropped.size[0]}x{cropped.size[1]}")
    return cropped


def convert_to_webp(image: Image.Image):
    """Converts a PIL Image object to WebP format in a BytesIO object."""
    byte_arr = io.BytesIO()
    try:
        # Use optimize=True for potentially smaller file size, and specify quality
        image.save(byte_arr, format='WEBP', optimize=True, quality=85)
        byte_arr.seek(0) # Rewind to the beginning of the stream
        logger.debug("Image converted to WebP.")
        return byte_arr
    except Exception as e:
        logger.error(f"Failed to convert image to WebP: {e}")
        raise # Re-raise the exception
