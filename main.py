# main.py
import os
import shutil
import uuid
import asyncio
from io import BytesIO
from datetime import datetime
import logging

from fastapi import FastAPI, File, UploadFile, HTTPException, status, Depends, Path
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image
import uvicorn
from pydantic import BaseModel
from typing import List

# Import aiofiles for asynchronous file operations
import aiofiles


# Assuming these are imported from other modules and are synchronous 'def' functions
# If any of these are already truly async (e.g., using aiobotocore, asyncpg),
# you should remove the asyncio.to_thread() wrapper for them and just use 'await' directly.
from nudenet import NudeDetector # NudeNet is typically synchronous
from user_models import User # Assuming User model is defined
from config import settings
from auth import auth_middleware
from cors import setup_cors 
from database import (
    save_image_record,
    db_pool, # db_pool itself doesn't need await, but operations using it do
    get_image_record_by_id,
    get_all_image_records_by_user_id,
    delete_image_record_by_id,
    update_image_record_url_by_id
)
from r2_storage import upload_file_to_r2, delete_file_from_r2
from image_utils import convert_to_webp, crop_image_to_aspect_ratio



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")


app = FastAPI()

# Configure CORS by calling the setup function from the core module
setup_cors(app)

# --- Pydantic Model for Image Records ---
class ImageRecord(BaseModel):
    id: str
    user_id: str
    r2_url: str
    object_name: str
    uploaded_at: datetime

    model_config = {
        "from_attributes": True
    }


# --- NudeNet Detector Initialization ---
model_path = settings.MODEL_PATH
detector = None
if not os.path.exists(model_path):
    print(f"WARNING: NudeNet model file not found at {model_path}. Nudity detection will be skipped.")
else:
    try:
        # NudeDetector initialization itself might be blocking, but it's usually done once at startup.
        detector = NudeDetector(model_path=model_path, inference_resolution=640)
        print("NudeNet detector initialized successfully.")
    except Exception as e:
        print(f"ERROR: Failed to initialize NudeNet detector: {e}")
        print("Nudity detection will be skipped.")
        detector = None


adult_content_labels = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_BREAST_AREOLA",
    "FEMALE_GENITALIA", "MALE_GENITALIA"
]

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024 # 10 MB

# --- Helper functions to run synchronous (blocking) code in a separate thread ---
# These functions use asyncio.to_thread to prevent blocking the event loop.
async def _run_blocking_pillow_op(func, *args, **kwargs):
    """Runs a Pillow (PIL) operation in a separate thread."""
    return await asyncio.to_thread(func, *args, **kwargs)

async def _run_blocking_nudity_detection(detector_instance, file_path):
    """Runs NudeNet detection in a separate thread."""
    return await asyncio.to_thread(detector_instance.detect, file_path)

async def _run_blocking_r2_op(func, *args, **kwargs):
    """Runs an R2 storage operation (upload/delete) in a separate thread."""
    return await asyncio.to_thread(func, *args, **kwargs)

async def _run_blocking_db_op(func, *args, **kwargs):
    """Runs a database operation in a separate thread."""
    return await asyncio.to_thread(func, *args, **kwargs)

async def _run_blocking_os_op(func, *args, **kwargs):
    """Runs an OS file system operation (like os.remove) in a separate thread."""
    return await asyncio.to_thread(func, *args, **kwargs)


# --- Health Check Endpoints ---
@app.get("/health")
async def health_check():
    return {"message": "ok from image service"}

@app.head("/health")
async def head():
    return JSONResponse(content={}, status_code=200)

@app.get("/", response_class=HTMLResponse)
async def main_form():
    return """
    <html>
        <head><title>Upload Image with Auth & Processing</title></head>
        <body>
            <h2>Upload an image (requires auth):</h2>
            <p>This form is for testing. Requires Authorization: Bearer [token] header.</p>
            <form action="/upload-image/" enctype="multipart/form-data" method="post">
                <input name="image" type="file" accept="image/*" required>
                <input type="submit" value="Upload">
            </form>
            <br/>
            <h2>Check image for nudity (no auth required):</h2>
            <form action="/detect-nudity/" enctype="multipart/form-data" method="post">
                <input name="image" type="file" accept="image/*" required>
                <input type="submit" value="Check Nudity">
            </form>
            <br/>
            <h2>Image Management (requires auth):</h2>
            <p>Use tools like curl or Postman for GET, PUT, DELETE on /images/me/ and /images/{image_id}</p>
        </body>
    </html>
    """

# --- Original Nudity Detection Endpoint (Made Async) ---
@app.post("/detect-nudity/")
async def detect_nudity(image: UploadFile = File(...)):
    """Checks an image for adult content using NudeNet."""
    temp_file_path = f"temp_detect_{uuid.uuid4().hex}_{image.filename}"
    is_adult = False
    try:
        if not image.content_type or not image.content_type.startswith("image/"):
            return JSONResponse(content={"is_adult_content": False, "detail": "Invalid file type."}, status_code=400)

        # Asynchronously read and write the file
        file_content = await image.read()
        async with aiofiles.open(temp_file_path, "wb") as temp_file:
            await temp_file.write(file_content)

        # Validate image (in thread)
        try:
            img_to_verify = await _run_blocking_pillow_op(Image.open, temp_file_path)
            await _run_blocking_pillow_op(lambda img: img.verify(), img_to_verify)
            await _run_blocking_pillow_op(lambda img: img.close(), img_to_verify)
        except Exception:
            return JSONResponse(content={"is_adult_content": False, "detail": "Invalid image file."}, status_code=400)

        # Nudity detection (in thread)
        if detector:
            result = await _run_blocking_nudity_detection(detector, temp_file_path)
            for item in result:
                if item.get("class") in adult_content_labels and item.get("score", 0) > 0.2:
                    is_adult = True
                    break
        else:
            logger.warning("NudeNet detector not available in /detect-nudity/. Skipping nudity detection.")

        return JSONResponse(content={"is_adult_content": is_adult}, status_code=200)

    except Exception as e:
        logger.error(f"Error during nudity detection in /detect-nudity/: {e}")
        return JSONResponse(content={"is_adult_content": False, "detail": "Internal server error."}, status_code=500)
    finally:
        if os.path.exists(temp_file_path):
            await _run_blocking_os_op(os.remove, temp_file_path)

# --- Image Upload Endpoint (Requires JWT Authentication) ---
@app.post("/upload-image/")
async def upload_image(
    image: UploadFile = File(...),
    user: User = Depends(auth_middleware)
):
    if not user or not getattr(user, "id", None):
        logger.error("User not found or unauthorized.")
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = str(user.id)
    logger.info(f"=== UploadImage START - User {user_id} authenticated ===")

    object_uuid = uuid.uuid4().hex
    object_name = f"uploads/{user_id}/{object_uuid}.webp"
    temp_file_path = f"temp_{object_uuid}_{image.filename}"

    try:
        # 1. Asynchronously read the file content
        file_content = await image.read()

        if len(file_content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File size exceeds limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB."
            )

        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

        # 2. Asynchronously save to temp file
        async with aiofiles.open(temp_file_path, "wb") as f_out:
            await f_out.write(file_content)

        # 3. Validate image (in thread)
        try:
            img_to_verify = await _run_blocking_pillow_op(Image.open, temp_file_path)
            await _run_blocking_pillow_op(lambda img: img.verify(), img_to_verify)
            await _run_blocking_pillow_op(lambda img: img.close(), img_to_verify)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted image file.")

        # 4. Nudity detection (in thread)
        if detector:
            try:
                detections = await _run_blocking_nudity_detection(detector, temp_file_path)
                for item in detections:
                    label = item.get("class")
                    score = item.get("score", 0)
                    if label in adult_content_labels and score > 0.2:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Adult content detected: {label} ({score:.2f})"
                        )
            except Exception as e:
                logger.error(f"NudeNet error: {e}")
                raise HTTPException(status_code=500, detail="Error during nudity detection.")
        else:
            logger.warning("NudeNet detector not initialized. Skipping nudity check.")

        # 5. Image processing (in thread)
        try:
            image_pil_for_processing = await _run_blocking_pillow_op(Image.open, temp_file_path)
            processed_image = await _run_blocking_pillow_op(crop_image_to_aspect_ratio, image_pil_for_processing)
            webp_bytes = await _run_blocking_pillow_op(convert_to_webp, processed_image)
            
            await _run_blocking_pillow_op(lambda img: img.close(), image_pil_for_processing)
            await _run_blocking_pillow_op(lambda img: img.close(), processed_image)
        except Exception as e:
            logger.error(f"Image processing error: {e}")
            raise HTTPException(status_code=500, detail="Failed to process image.")

        # 6. Upload to R2 (in thread)
        try:
            r2_url = await _run_blocking_r2_op(upload_file_to_r2, webp_bytes, object_name)
            if not r2_url:
                raise HTTPException(status_code=500, detail="Image uploaded but URL construction failed.")
        except Exception as e:
            logger.error(f"R2 upload error: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload image to storage.")

        # 7. Save to DB (in thread)
        logger.info("Attempting to save image record to DB.")
        try:
            image_uuid = await _run_blocking_db_op(save_image_record, user_id=user_id, r2_url=r2_url, object_name=object_name)
            logger.info(f"Result from save_image_record: {image_uuid}")
            if not image_uuid:
                logger.error("save_image_record returned a falsey value (e.g., None or empty UUID).")
                raise Exception("Database record was not created (save_image_record returned falsey).")
        except Exception as e:
            logger.error(f"DB save error during save_image_record call: {e}")
            try:
                # Cleanup R2 object if DB save fails (in thread)
                await _run_blocking_r2_op(delete_file_from_r2, object_name)
                logger.info(f"Cleaned up R2 object {object_name} after DB save failure.")
            except Exception as cleanup_e:
                logger.critical(f"Failed to clean up R2 object {object_name}: {cleanup_e}")
            raise HTTPException(status_code=500, detail="Failed to save image info to database.")

        logger.info(f"Image UUID obtained for response: {image_uuid}")

        return JSONResponse(
            content={"image_id": str(image_uuid)},
            status_code=201
        )

        # return JSONResponse(
        #     content={"message": "Upload successful", "image_id": str(image_uuid), "r2_url": r2_url},
        #     status_code=201
        # )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unhandled error during upload: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
    finally:
        if os.path.exists(temp_file_path):
            await _run_blocking_os_op(os.remove, temp_file_path)


# --- GET User's Images (Made Async) ---
@app.get("/images/me/", response_model=List[ImageRecord])
async def get_my_images(user_id: str = Depends(auth_middleware)):
    logger.info(f"Getting images for user {user_id}")
    try:
        # Run DB operation in a separate thread
        images = await _run_blocking_db_op(get_all_image_records_by_user_id, user_id)
        return images
    except Exception as e:
        logger.error(f"Error getting images for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve images.")

# --- GET Specific Image (Made Async) ---
@app.get("/images/{image_id}", response_model=ImageRecord)
async def get_image_by_id(
    image_id: str = Path(..., description="The UUID of the image to retrieve"),
    user_id: str = Depends(auth_middleware)
):
    logger.info(f"Getting image {image_id} for user {user_id}")
    try:
        # Run DB operation in a separate thread
        image_record = await _run_blocking_db_op(get_image_record_by_id, user_id, image_id)
        if image_record is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        return image_record
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error getting image UUID {image_id} for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image.")


# --- DELETE Specific Image (Made Async) ---
@app.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(
    image_id: str = Path(..., description="The UUID of the image to delete"),
    user_id: str = Depends(auth_middleware)
):
    """
    Delete a specific image record and the corresponding file from storage for the authenticated user.
    """
    old_object_name = None
    try:
        # 1. Get the image record to retrieve the R2 object name (in thread)
        image_record = await _run_blocking_db_op(get_image_record_by_id, user_id, image_id)
        if image_record is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        old_object_name = image_record.get("object_name")

        if not old_object_name:
            logger.error(f"Error: object_name missing for image UUID {image_id} for user {user_id}")
            raise HTTPException(status_code=500, detail="Image record is incomplete (missing object name). Cannot delete from storage.")

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error retrieving image record {image_id} for deletion for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image details for deletion.")

    # 2. Delete the file from R2 storage (in thread)
    try:
        await _run_blocking_r2_op(delete_file_from_r2, old_object_name)
        logger.info(f"Successfully deleted old R2 object: {old_object_name}")
    except Exception as e:
        logger.error(f"Error deleting R2 object {old_object_name} for image UUID {image_id} (user {user_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to delete image file from storage.")

    # 3. Delete the record from the database (in thread)
    try:
        deleted_from_db = await _run_blocking_db_op(delete_image_record_by_id, user_id, image_id)
        if not deleted_from_db:
            logger.warning(f"DB record {image_id} not found for deletion for user {user_id} after R2 attempt.")
            raise HTTPException(status_code=404, detail="Image record not found in database.")

    except Exception as e:
        logger.error(f"Error deleting image record {image_id} from DB for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete image record from database.")

    return # Return 204 No Content on successful deletion


# --- PUT/Update Specific Image (Made Async) ---
@app.put("/images/{image_id}", response_model=ImageRecord)
async def update_image(
    image_id: str = Path(..., description="The UUID of the image to update"),
    file: UploadFile = File(...), # New file to replace the old one
    user_id: str = Depends(auth_middleware)
):
    """
    Update a specific image record by replacing the image file and updating the storage URL/object_name.
    Performs validation, processing, uploads the new file, updates the DB, and deletes the old file.
    """
    old_image_record = None
    old_object_name = None
    temp_file_path = None
    new_webp_bytes = None
    new_r2_url = None
    new_object_name = None

    try:
        # 1. Get the existing image record to verify ownership and get old object name (in thread)
        old_image_record = await _run_blocking_db_op(get_image_record_by_id, user_id, image_id)
        if old_image_record is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        old_object_name = old_image_record.get("object_name")

        if not old_object_name:
            logger.error(f"Error: object_name missing for image UUID {image_id} for user {user_id} during update attempt.")
            raise HTTPException(status_code=500, detail="Image record is incomplete (missing object name). Cannot update.")

        # 2. Validate and process the NEW uploaded file (similar to /upload-image/)
        # Asynchronously read file content
        new_file_content = await file.read()

        if len(new_file_content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"New file size exceeds the limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.")

        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid new file type. Only images are allowed.")

        temp_file_path = f"temp_update_{uuid.uuid4().hex}_{file.filename}"
        # Asynchronously write to temp file
        async with aiofiles.open(temp_file_path, "wb") as f_out:
            await f_out.write(new_file_content)

        # Validate image (in thread)
        try:
            img_to_verify = await _run_blocking_pillow_op(Image.open, temp_file_path)
            await _run_blocking_pillow_op(lambda img: img.verify(), img_to_verify)
            await _run_blocking_pillow_op(lambda img: img.close(), img_to_verify)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted new image file.")

        # Nudity detection (in thread)
        if detector:
            try:
                detections = await _run_blocking_nudity_detection(detector, temp_file_path)
                for item in detections:
                    label = item.get("class")
                    score = item.get("score", 0)
                    if label in adult_content_labels and score > 0.2:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Adult content detected in new image: {label} ({score:.2f})"
                        )
            except Exception as e:
                logger.error(f"NudeNet error during update: {e}")
                raise HTTPException(status_code=500, detail="Error during nudity detection for new image.")
        else:
            logger.warning("NudeNet detector not initialized. Skipping nudity check for new image.")

        # Image processing (in thread)
        try:
            image_pil_for_processing = await _run_blocking_pillow_op(Image.open, temp_file_path)
            processed_image = await _run_blocking_pillow_op(crop_image_to_aspect_ratio, image_pil_for_processing)
            new_webp_bytes = await _run_blocking_pillow_op(convert_to_webp, processed_image)
            
            await _run_blocking_pillow_op(lambda img: img.close(), image_pil_for_processing)
            await _run_blocking_pillow_op(lambda img: img.close(), processed_image)
        except Exception as e:
            logger.error(f"New image processing error during update: {e}")
            raise HTTPException(status_code=500, detail="Failed to process new image.")

        # 3. Upload the NEW processed image to R2 (in thread)
        new_object_uuid = uuid.uuid4().hex
        new_object_name = f"uploads/{user_id}/{new_object_uuid}.webp"
        try:
            if new_webp_bytes is None:
                raise Exception("Processed new image bytes not available for upload.")
            new_r2_url = await _run_blocking_r2_op(upload_file_to_r2, new_webp_bytes, new_object_name)
            if not new_r2_url:
                raise HTTPException(status_code=500, detail="New image uploaded but URL construction failed.")
        except Exception as e:
            logger.error(f"New R2 upload error during update: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload new image to storage.")

        # 4. Update the database record with the new R2 URL and object name (in thread)
        try:
            updated_in_db = await _run_blocking_db_op(update_image_record_url_by_id, user_id, image_id, new_r2_url, new_object_name)
            if not updated_in_db:
                logger.warning(f"DB record UUID {image_id} not found for update for user {user_id}.")
                # CRITICAL INCONSISTENCY: New file uploaded, but DB record wasn't updated.
                # Attempt to clean up the NEWLY uploaded R2 file before raising error.
                try:
                    if new_object_name:
                        await _run_blocking_r2_op(delete_file_from_r2, new_object_name)
                        logger.info(f"Cleaned up newly uploaded R2 object {new_object_name} after DB update failure.")
                except Exception as cleanup_e:
                    logger.critical(f"CRITICAL: Failed to clean up newly uploaded R2 object {new_object_name} after DB update failure: {cleanup_e}")
                raise HTTPException(status_code=404, detail="Image record not found in database.")
        except Exception as e:
            logger.error(f"DB update error for image UUID {image_id} for user {user_id}: {e}")
            # CRITICAL INCONSISTENCY: New file uploaded, but DB update failed.
            # Attempt cleanup of the NEWLY uploaded R2 file.
            try:
                if new_object_name:
                    await _run_blocking_r2_op(delete_file_from_r2, new_object_name)
                    logger.info(f"Cleaned up newly uploaded R2 object {new_object_name} after DB update exception.")
            except Exception as cleanup_e:
                logger.critical(f"CRITICAL: Failed to clean up newly uploaded R2 object {new_object_name} after DB update exception: {cleanup_e}")
            raise HTTPException(status_code=500, detail="Failed to update image record in database.")


        # 5. Delete the OLD file from R2 storage (in thread - best effort, log if fails)
        if old_object_name:
            try:
                await _run_blocking_r2_op(delete_file_from_r2, old_object_name)
                logger.info(f"Successfully deleted old R2 object: {old_object_name}")
            except Exception as e:
                logger.warning(f"Warning: Failed to delete old R2 object {old_object_name} for image UUID {image_id} (user {user_id}): {e}")


        # 6. Success - Return the updated record (in thread)
        updated_record = await _run_blocking_db_op(get_image_record_by_id, user_id, image_id)
        if updated_record is None:
            logger.critical(f"CRITICAL: Updated record UUID {image_id} not found immediately after update for user {user_id}.")
            raise HTTPException(status_code=500, detail="Failed to retrieve updated image record.")

        return updated_record


    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"An unhandled error occurred during image update for UUID {image_id} (user {user_id}): {e}")
        # Final catch-all cleanup attempt for the NEWLY uploaded file if an unexpected error occurred
        try:
            if new_object_name:
                await _run_blocking_r2_op(delete_file_from_r2, new_object_name)
                logger.info(f"Cleaned up newly uploaded R2 object {new_object_name} after unexpected update failure.")
        except Exception as cleanup_e:
            logger.critical(f"CRITICAL: Failed to clean up newly uploaded R2 object {new_object_name} after unexpected update failure: {cleanup_e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during update.")
    finally:
        if os.path.exists(temp_file_path):
            await _run_blocking_os_op(os.remove, temp_file_path)


# Optional: Add a shutdown event to close the database pool
@app.on_event("shutdown")
async def shutdown_event():
    # db_pool.closeall() is likely synchronous, but acceptable at shutdown
    if db_pool:
        db_pool.closeall()
        logger.info("PostgreSQL connection pool closed.")


# --- Run the application ---
if __name__ == "__main__":
    ai_models_dir = os.path.join(os.path.dirname(__file__), "ai_models")
    if not os.path.exists(ai_models_dir):
        os.makedirs(ai_models_dir)
        logger.info(f"Created directory: {ai_models_dir}")

    if not os.path.exists(settings.MODEL_PATH):
        logger.error(f"Error: NudeNet model file not found at {settings.MODEL_PATH}. Please download it.")
        logger.error("You can typically download it from the NudeNet repository or instructions.")

    uvicorn.run(app, host="0.0.0.0", port=8083)