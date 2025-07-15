# image_router.py
import asyncio
import logging
from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, Path, HTTPException, Body

# Local imports
from user_models import User
from auth import auth_middleware
from schemas import ImageRecord, BulkDeleteRequest, UploadResponse, BulkUploadResponse
from async_utils import run_blocking_io
from image_services import process_and_upload_image, delete_image_from_storage_and_db
from database import get_all_image_records_by_user_id, get_image_record_by_id

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/images",
    tags=["images"],
    dependencies=[Depends(auth_middleware)]
)


@router.post("/upload-multiple/", response_model=BulkUploadResponse, status_code=200) # Changed to 200 OK
async def upload_multiple_images(
    user: User = Depends(auth_middleware),
    images: List[UploadFile] = File(...)
):
    """
    Upload multiple images concurrently.
    This endpoint processes all images and returns a result for each,
    even if some uploads fail.
    """
    user_id = str(user.id)
    logger.info(f"User {user_id} initiated bulk upload for {len(images)} images.")

    # A "safe wrapper" to process each file and catch its own exceptions.
    # This prevents one failure from stopping the entire batch.
    async def safe_process_image(image: UploadFile, user_id: str):
        try:
            # On success, this returns the result dictionary from the service
            return await process_and_upload_image(image, user_id)
        except HTTPException as e:
            # On failure, catch the exception and return a formatted error message
            logger.warning(f"Failed to process {image.filename} for user {user_id}: {e.detail}")
            return {"success": False, "filename": image.filename, "detail": e.detail}

    # Create a task for each safe wrapper function
    upload_tasks = [safe_process_image(image, user_id) for image in images]
    
    # Run all tasks. gather will no longer raise an exception.
    results = await asyncio.gather(*upload_tasks)
    
    # Optionally, determine the overall status code
    # For simplicity, we now return 200 OK with a detailed body.
    return {"results": results}

# ---
    
@router.post("/delete-multiple/", status_code=200)
async def delete_multiple_images(
    user: User = Depends(auth_middleware),
    payload: BulkDeleteRequest = Body(...)
):
    """
    Delete multiple images concurrently.
    This endpoint attempts to delete all specified images and returns
    a result for each operation.
    """
    user_id = str(user.id)
    image_ids = payload.image_ids
    logger.info(f"User {user_id} initiated bulk delete for {len(image_ids)} images.")

    # Safe wrapper for the delete operation
    async def safe_delete_image(image_id: str, user_id: str):
        try:
            # The service function raises an exception on failure
            await delete_image_from_storage_and_db(image_id, user_id)
            return {"success": True, "image_id": image_id, "detail": "Deleted successfully."}
        except HTTPException as e:
            logger.warning(f"Failed to delete image {image_id} for user {user_id}: {e.detail}")
            return {"success": False, "image_id": image_id, "detail": e.detail}

    delete_tasks = [safe_delete_image(image_id, user_id) for image_id in image_ids]
    results = await asyncio.gather(*delete_tasks)

    # Check if any of the operations failed
    all_successful = all(res['success'] for res in results)

    return {
        "detail": "Bulk delete operation completed.",
        "status": "success" if all_successful else "partial",
        "results": results
    }

# --- Refactored Single Endpoints ---

@router.delete("/{image_id}", status_code=204) # 204 No Content is standard for successful DELETE
async def delete_single_image(
    image_id: str = Path(..., description="UUID of the image to delete"),
    user: User = Depends(auth_middleware)
):
    """
    Delete a single image. This now correctly handles exceptions from the service layer.
    """
    user_id = str(user.id)
    logger.info(f"User {user_id} requested delete for image {image_id}")
    try:
        await delete_image_from_storage_and_db(image_id, user_id)
        # On success, a 204 response with no body is returned automatically.
    except HTTPException as e:
        # Re-raise the exception and let FastAPI handle formatting the error response.
        # This is much cleaner than manually checking dictionary keys.
        raise e

# --- Unchanged Endpoints ---

@router.get("/me/", response_model=List[ImageRecord])
async def get_my_images(user: User = Depends(auth_middleware)):
    """Retrieve all image records for the authenticated user."""
    user_id = str(user.id)
    try:
        images = await run_blocking_io(get_all_image_records_by_user_id, user_id)
        return images
    except Exception as e:
        logger.error(f"Error getting images for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve images.")

@router.get("/{image_id}", response_model=ImageRecord)
async def get_image_by_id_endpoint(
    image_id: str = Path(..., description="The UUID of the image to retrieve"),
    user: User = Depends(auth_middleware)
):
    """Retrieve a specific image record by its ID."""
    user_id = str(user.id)
    try:
        image_record = await run_blocking_io(get_image_record_by_id, user_id, image_id)
        if image_record is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        return image_record
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting image {image_id} for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image.")