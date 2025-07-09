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
    dependencies=[Depends(auth_middleware)] # Apply auth to all routes in this router
)

# --- NEW: Bulk Image Upload Endpoint ---
@router.post("/upload-multiple/", response_model=BulkUploadResponse, status_code=201)
async def upload_multiple_images(
    user: User = Depends(auth_middleware),
    images: List[UploadFile] = File(...)
):
    """
    Upload multiple images concurrently.
    Each image is processed and uploaded in parallel.
    """
    user_id = str(user.id)
    logger.info(f"User {user_id} initiated bulk upload for {len(images)} images.")

    # Create a task for each image upload
    upload_tasks = [process_and_upload_image(image, user_id) for image in images]

    # Run all tasks concurrently and wait for them to complete
    results = await asyncio.gather(*upload_tasks)

    return {"results": results}

# --- NEW: Bulk Image Delete Endpoint ---
@router.post("/delete-multiple/")
async def delete_multiple_images(
    user: User = Depends(auth_middleware),
    payload: BulkDeleteRequest = Body(...)
):
    """
    Delete multiple images concurrently based on a list of image IDs.
    """
    user_id = str(user.id)
    image_ids = payload.image_ids
    logger.info(f"User {user_id} initiated bulk delete for {len(image_ids)} images.")

    # Create a task for each image deletion
    delete_tasks = [delete_image_from_storage_and_db(image_id, user_id) for image_id in image_ids]

    # Run all tasks concurrently
    results = await asyncio.gather(*delete_tasks)

    # Check if all deletions were successful
    all_successful = all(res['success'] for res in results)

    return {
        "detail": "Bulk delete operation completed.",
        "status": "partial" if not all_successful else "success",
        "results": results
    }

# --- Existing Endpoints (Refactored) ---

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

@router.delete("/{image_id}")
async def delete_single_image(
    image_id: str = Path(..., description="UUID of the image to delete"),
    user: User = Depends(auth_middleware)
):
    """Delete a single image."""
    user_id = str(user.id)
    logger.info(f"User {user_id} requested delete for image {image_id}")
    result = await delete_image_from_storage_and_db(image_id, user_id)
    if not result["success"]:
        # Re-raise as HTTPException to let FastAPI handle the response
        if "not found" in result["detail"]:
             raise HTTPException(status_code=404, detail=result["detail"])
        else:
             raise HTTPException(status_code=500, detail=result["detail"])

    return {"message": result["detail"]}