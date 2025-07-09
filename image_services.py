# image_services.py
import os
import uuid
import logging
from io import BytesIO
from typing import List, Dict

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

logger = logging.getLogger(__name__)
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

async def process_and_upload_image(image: UploadFile, user_id: str) -> Dict:
    """
    Handles the complete lifecycle of uploading a single image:
    validation, nudity detection, processing, uploading to R2, and saving to DB.
    """
    temp_file_path = f"temp_{uuid.uuid4().hex}_{image.filename}"
    detector = get_detector()

    try:
        # 1. Validate file type and size
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

        file_content = await image.read()
        if len(file_content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File size exceeds limit of 10 MB.")

        # 2. Save to temp file and validate image integrity
        async with aiofiles.open(temp_file_path, "wb") as f_out:
            await f_out.write(file_content)

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
        object_name = f"uploads/{user_id}/{uuid.uuid4().hex}.webp"
        r2_url = await run_blocking_io(upload_file_to_r2, webp_bytes, object_name)
        if not r2_url:
            raise HTTPException(status_code=500, detail="Failed to get URL after upload.")

        # 6. Save record to database
        image_uuid = await run_blocking_io(save_image_record, user_id=user_id, r2_url=r2_url, object_name=object_name)
        if not image_uuid:
            await run_blocking_io(delete_file_from_r2, object_name) # Cleanup R2
            raise HTTPException(status_code=500, detail="Failed to save image record to database.")

        return {"success": True, "image_id": str(image_uuid), "filename": image.filename}

    except HTTPException as e:
        return {"success": False, "filename": image.filename, "detail": e.detail}
    except Exception as e:
        logger.error(f"Unexpected error processing {image.filename}: {e}")
        return {"success": False, "filename": image.filename, "detail": "An unexpected server error occurred."}
    finally:
        # 7. Cleanup temp file
        if os.path.exists(temp_file_path):
            await run_blocking_io(os.remove, temp_file_path)


async def delete_image_from_storage_and_db(image_id: str, user_id: str) -> Dict:
    """
    Handles the complete lifecycle of deleting an image:
    DB lookup, R2 deletion, nullifying references, and DB record deletion.
    """
    try:
        # 1. Lookup image record
        image_record = await run_blocking_io(get_image_record_by_id, user_id, image_id)
        if not image_record:
            raise HTTPException(status_code=404, detail="Image not found or you do not have permission to delete it.")

        object_name = image_record["object_name"]

        # 2. Delete from R2 storage
        await run_blocking_io(delete_file_from_r2, object_name)
        logger.info(f"Deleted object from R2: {object_name}")

        # 3. Nullify any foreign key references in other tables
        await run_blocking_io(nullify_service_image_reference, image_id)

        # 4. Delete the record from the images table
        deleted = await run_blocking_io(delete_image_record_by_id, user_id, image_id)
        if not deleted:
            # This case is unlikely if the initial lookup succeeded but is good practice to handle.
            raise HTTPException(status_code=500, detail="Image found but could not be deleted from the database.")

        return {"success": True, "image_id": image_id, "detail": "Image deleted successfully."}

    except HTTPException as e:
        return {"success": False, "image_id": image_id, "detail": e.detail}
    except Exception as e:
        logger.error(f"Failed to delete image {image_id}: {e}")
        return {"success": False, "image_id": image_id, "detail": "An unexpected server error occurred during deletion."}