# image_services.py
import os
import uuid
import logging
from typing import Dict

import aiofiles
from fastapi import UploadFile, HTTPException
from PIL import Image

# Local imports
from async_utils import run_blocking_io
from dependencies import get_detector, ADULT_CONTENT_LABELS
from r2_storage import upload_file_to_r2, delete_file_from_r2
from image_utils import convert_to_webp, crop_image_to_aspect_ratio
from database import (
    save_image_record,
    get_image_record_by_id,
    delete_image_record_by_id,
    nullify_service_image_reference
)

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/bmp",
    "image/tiff",
}

logger = logging.getLogger(__name__)
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

async def process_and_upload_image(image: UploadFile, user_id: str) -> Dict[str, any]:
    temp_file_path = f"temp_{uuid.uuid4().hex}"
    detector = get_detector()

    try:
        # 1. Stream file to disk and validate size on the fly.
        # This is more memory-efficient and robust than image.read().
        # if image.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        #     logger.warning(f"Declared content type '{image.content_type}' not in allowed list for {image.filename}")
        #     raise HTTPException(status_code=400, detail="Unsupported image format.")

        current_size = 0
        async with aiofiles.open(temp_file_path, "wb") as f:
            while chunk := await image.read(1024 * 1024):  # Read in 1MB chunks
                current_size += len(chunk)
                if current_size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="File size exceeds the 10 MB limit.")
                await f.write(chunk)
        
        # 2. Validate image integrity
        img_to_verify = await run_blocking_io(Image.open, temp_file_path)
        await run_blocking_io(img_to_verify.verify)
        await run_blocking_io(img_to_verify.close)

        # 3. Nudity detection
        if detector:
            detections = await run_blocking_io(detector.detect, temp_file_path)
            for item in detections:
                if item.get("class") in ADULT_CONTENT_LABELS and item.get("score", 0) > 0.2:
                    raise HTTPException(status_code=400, detail=f"Adult content detected: {item.get('class')}")

        # 4. Image processing (crop and convert to WebP)
        image_pil = await run_blocking_io(Image.open, temp_file_path)
        processed_image = await run_blocking_io(crop_image_to_aspect_ratio, image_pil)
        webp_bytes = await run_blocking_io(convert_to_webp, processed_image)
        await run_blocking_io(image_pil.close)
        await run_blocking_io(processed_image.close)

        # 5. Upload to R2 storage
        object_name = f"{uuid.uuid4().hex}.webp"
        r2_url = await run_blocking_io(upload_file_to_r2, webp_bytes, object_name)
        if not r2_url:
            raise HTTPException(status_code=500, detail="Failed to upload to storage.")

        # 6. Save record to database
        image_uuid = await run_blocking_io(save_image_record, user_id=user_id, r2_url=r2_url, object_name=object_name)
        if not image_uuid:
            await run_blocking_io(delete_file_from_r2, object_name)  # Cleanup R2
            raise HTTPException(status_code=500, detail="Failed to save image record.")

        return {"success": True, "image_id": str(image_uuid), "filename": image.filename}

    except HTTPException as e:
        # Re-raise HTTPException to be handled by the endpoint
        logger.warning(f"Validation/processing error for {image.filename}: {e.detail}")
        # The endpoint should catch this and format the response
        raise e
    except Exception as e:
        # For unexpected errors, log the full traceback for debugging
        logger.error(f"Unexpected error processing {image.filename}", exc_info=True)
        # Raise a generic HTTP error
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")
    finally:
        # 7. Cleanup temp file robustly
        if os.path.exists(temp_file_path):
            await run_blocking_io(os.remove, temp_file_path)


async def delete_image_from_storage_and_db(image_id: str, user_id: str):
    try:
        # 1. Lookup image record
        image_record = await run_blocking_io(get_image_record_by_id, user_id, image_id)
        if not image_record:
            raise HTTPException(status_code=404, detail="Image not found or permission denied.")

        object_name = image_record["object_name"]

        # 2. Delete from R2 storage
        await run_blocking_io(delete_file_from_r2, object_name)
        logger.info(f"Deleted object from R2: {object_name}")

        # 3. Nullify foreign key references
        await run_blocking_io(nullify_service_image_reference, image_id)

        # 4. Delete the primary image record
        await run_blocking_io(delete_image_record_by_id, user_id, image_id)

    except HTTPException:
        # Re-raise known HTTP exceptions to be handled by the router
        raise
    except Exception as e:
        logger.error(f"Failed to delete image {image_id} for user {user_id}.", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected server error occurred during deletion.")