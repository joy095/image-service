# main.py
from fastapi import FastAPI, File, UploadFile, HTTPException, status, Depends, Path # Import Path
from fastapi.responses import HTMLResponse, JSONResponse
# Assuming nudenet, shutil, os, PIL, uvicorn, uuid, io are already imported
from nudenet import NudeDetector
import shutil
import os
from PIL import Image
import uvicorn
import uuid # To generate unique filenames
import io # To work with image data in memory
from typing import List
from pydantic import BaseModel # Import BaseModel for response models
from datetime import datetime # Import datetime for the model

# Import your configuration and other modules
from config import settings
# Import the JWT authentication dependency
from auth import get_current_user_id
# Import the database functions (updated)
from database import (
    save_image_record,
    db_pool,
    get_image_record_by_id,
    get_all_image_records_by_user_id,
    delete_image_record_by_id,
    update_image_record_url_by_id
)
# Import the r2_storage functions
from r2_storage import upload_file_to_r2, delete_file_from_r2
# Import image_utils functions
from image_utils import convert_to_webp, crop_image_to_aspect_ratio


app = FastAPI()

# --- Pydantic Model for Image Records ---
class ImageRecord(BaseModel):
    # ID is now a string (UUID)
    id: str
    user_id: str
    r2_url: str
    object_name: str # Include object name in the model
    uploaded_at: datetime # Include uploaded_at as datetime

    # Pydantic Config for ORM mode or similar if needed, but dict should work
    class Config:
        orm_mode = True # Allows Pydantic to read data like an ORM object


# --- NudeNet Detector Initialization (from your original code) ---
# Define the model path from settings
model_path = settings.MODEL_PATH

# Check if the model file exists, and initialize the detector if it does
detector = None
if not os.path.exists(model_path):
    print(f"WARNING: NudeNet model file not found at {model_path}. Nudity detection will be skipped.")
else:
    try:
        detector = NudeDetector(model_path=model_path, inference_resolution=640)
        print("NudeNet detector initialized successfully.")
    except Exception as e:
        print(f"ERROR: Failed to initialize NudeNet detector: {e}")
        print("Nudity detection will be skipped.")
        detector = None


# List of adult content labels to check for
adult_content_labels = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_BREAST_AREOLA",
    "FEMALE_GENITALIA", "MALE_GENITALIA"
]

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024 # 10 MB

# --- Health Check Endpoints ---
@app.get("/health")
async def health_check():
    return {"message": "ok from image service"}

@app.head("/health")
async def head():
    return JSONResponse(content={}, status_code=200)

@app.get("/", response_class=HTMLResponse)
async def main_form():
     # Keep the form as is, it's just a simple test interface
     return """
     <html>
         <head><title>Upload Image with Auth & Processing</title></head>
         <body>
             <h2>Upload an image (requires auth):</h2>
             <p>This form is for testing. Requires Authorization: Bearer [token] header.</p>
             <form action="/upload-image/" enctype="multipart/form-data" method="post">
                 <input name="file" type="file" accept="image/*" required>
                 <input type="submit" value="Upload">
             </form>
             <br/>
              <h2>Check image for nudity (no auth required):</h2>
             <form action="/detect-nudity/" enctype="multipart/form-data" method="post">
                 <input name="file" type="file" accept="image/*" required>
                 <input type="submit" value="Check Nudity">
             </form>
              <br/>
              <h2>Image Management (requires auth):</h2>
              <p>Use tools like curl or Postman for GET, PUT, DELETE on /images/me/ and /images/{image_id}</p>
         </body>
     </html>
     """

# --- Original Nudity Detection Endpoint (Optional - keep or remove) ---
@app.post("/detect-nudity/")
async def detect_nudity(file: UploadFile = File(...)):
    """Checks an image for adult content using NudeNet."""
    # This endpoint remains unchanged as it doesn't interact with the DB/Auth
    temp_file_path = f"temp_detect_{uuid.uuid4().hex}_{file.filename}"
    is_adult = False
    try:
        if not file.content_type or not file.content_type.startswith("image/"):
             return JSONResponse(content={"is_adult_content": False, "detail": "Invalid file type."}, status_code=400)

        with open(temp_file_path, "wb") as temp_file:
             shutil.copyfileobj(file.file, temp_file)

        try:
             img = Image.open(temp_file_path)
             img.verify()
             img.close()
        except Exception:
            return JSONResponse(content={"is_adult_content": False, "detail": "Invalid image file."}, status_code=400)

        if detector:
             result = detector.detect(temp_file_path)
             for item in result:
                 if item.get("class") in adult_content_labels and item.get("score", 0) > 0.2:
                      is_adult = True
                      break
        else:
             print("NudeNet detector not available in /detect-nudity/. Skipping nudity detection.")

        return JSONResponse(content={"is_adult_content": is_adult}, status_code=200)

    except Exception as e:
        print(f"Error during nudity detection in /detect-nudity/: {e}")
        return JSONResponse(content={"is_adult_content": False, "detail": "Internal server error."}, status_code=500)
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

# --- Image Upload Endpoint (Requires JWT Authentication) ---
@app.post("/upload-image/")
async def upload_image(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id)
):
    """
    Upload an image, detect nudity, process (crop + webp), upload to R2, save info to DB.
    """
    object_uuid = uuid.uuid4().hex
    # Use user_id in object name path for organization in R2
    object_name = f"uploads/{user_id}/{object_uuid}.webp"
    temp_file_path = f"temp_{object_uuid}_{file.filename}"

    try:
        if file.size > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File size exceeds the limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.")

        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

        with open(temp_file_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        try:
            img = Image.open(temp_file_path)
            img.verify()
            img.close()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted image file.")

        if detector:
            try:
                detections = detector.detect(temp_file_path)
                for item in detections:
                    label = item.get("class")
                    score = item.get("score", 0)
                    if label in adult_content_labels and score > 0.2:
                         raise HTTPException(
                              status_code=400,
                              detail=f"Adult content detected: {label} ({score:.2f})"
                         )
            except Exception as e:
                print(f"NudeNet error: {e}")
                raise HTTPException(status_code=500, detail="Error during nudity detection.")
        else:
            print("NudeNet detector not initialized. Skipping nudity check.")


        webp_bytes = None
        try:
            image = Image.open(temp_file_path)
            processed_image = crop_image_to_aspect_ratio(image)
            webp_bytes = convert_to_webp(processed_image)
            image.close()
            processed_image.close()
        except Exception as e:
            print(f"Image processing error: {e}")
            raise HTTPException(status_code=500, detail="Failed to process image.")

        r2_url = None
        try:
            if webp_bytes is None:
                 raise Exception("Processed image bytes not available for upload.")
            r2_url = upload_file_to_r2(webp_bytes, object_name)
            if not r2_url:
                 raise HTTPException(status_code=500, detail="Image uploaded but URL construction failed.")
        except Exception as e:
            print(f"R2 upload error: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload image to storage.")

        # Save to DB - pass object_name and get UUID string back
        image_uuid = None
        try:
            image_uuid = save_image_record(user_id=user_id, r2_url=r2_url, object_name=object_name)
            if image_uuid is None:
                 raise Exception("Database record was not created.")
        except Exception as e:
            print(f"DB save error: {e}")
            # Consider R2 cleanup here if DB save fails
            try:
                 if object_name:
                     # Attempt to delete the file uploaded to R2 if DB save failed
                     delete_file_from_r2(object_name)
                     print(f"Cleaned up R2 object {object_name} after DB save failure.")
            except Exception as cleanup_e:
                 print(f"CRITICAL: Failed to clean up R2 object {object_name} after DB save failure: {cleanup_e}")

            raise HTTPException(status_code=500, detail="Failed to save image info to database.")

        # Success - return UUID as string
        return JSONResponse(content={"message": "Upload successful", "image_id": image_uuid, "r2_url": r2_url}, status_code=201)

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"An unhandled error occurred during image upload: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


# --- GET User's Images ---
@app.get("/images/me/", response_model=List[ImageRecord])
async def get_my_images(user_id: str = Depends(get_current_user_id)):
    """
    Get all image records for the authenticated user.
    """
    try:
        images = get_all_image_records_by_user_id(user_id)
        return images
    except Exception as e:
        print(f"Error getting images for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve images.")

# --- GET Specific Image --- # <--- THIS SHOULD COME SECOND
@app.get("/images/{image_id}", response_model=ImageRecord)
async def get_image_by_id(
    image_id: str = Path(..., description="The UUID of the image to retrieve"),
    user_id: str = Depends(get_current_user_id)
):
    """
    Get a specific image record by UUID for the authenticated user.
    """
    try:
        image_record = get_image_record_by_id(user_id, image_id)
        if image_record is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        return image_record
    except HTTPException as he:
         raise he
    except Exception as e:
        print(f"Error getting image UUID {image_id} for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image.")


# --- DELETE Specific Image ---
@app.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(
    # image_id is now a string (UUID)
    image_id: str = Path(..., description="The UUID of the image to delete"),
    user_id: str = Depends(get_current_user_id)
):
    """
    Delete a specific image record and the corresponding file from storage for the authenticated user.
    """
    # 1. Get the image record to retrieve the R2 object name
    try:
        image_record = get_image_record_by_id(user_id, image_id)
        if image_record is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        object_name_to_delete = image_record.get("object_name")

        if not object_name_to_delete:
             # This indicates a problem with the DB schema or data if object_name is missing
             print(f"Error: object_name missing for image UUID {image_id} for user {user_id}")
             # Decide how to handle - cannot delete from R2. Either fail or proceed only with DB delete.
             # Failing is safer to avoid orphan DB records if R2 deletion is expected.
             raise HTTPException(status_code=500, detail="Image record is incomplete (missing object name). Cannot delete from storage.")


    except HTTPException as he:
         raise he
    except Exception as e:
        print(f"Error retrieving image record {image_id} for deletion for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image details for deletion.")

    # 2. Delete the file from R2 storage
    try:
        # Attempt R2 deletion first. If it fails (except NoSuchKey), the request fails.
        delete_file_from_r2(object_name_to_delete)
        # Note: delete_file_from_r2 handles NoSuchKey internally by logging a warning and returning False/raising error based on its logic.
        # We proceed to DB deletion regardless, but an R2 deletion error will stop the request here.

    except Exception as e:
        print(f"Error deleting R2 object {object_name_to_delete} for image UUID {image_id} (user {user_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to delete image file from storage.")

    # 3. Delete the record from the database
    try:
        deleted_from_db = delete_image_record_by_id(user_id, image_id)
        if not deleted_from_db:
             # Should not happen if initial get_image_record_by_id succeeded, but check.
             print(f"Warning: DB record {image_id} not found for deletion for user {user_id} after R2 attempt.")
             raise HTTPException(status_code=404, detail="Image record not found in database.")

    except Exception as e:
        print(f"Error deleting image record {image_id} from DB for user {user_id}: {e}")
        # Critical: If DB deletion fails but R2 succeeded, you have an orphan R2 file.
        # Requires manual cleanup or a background process.
        raise HTTPException(status_code=500, detail="Failed to delete image record from database.")

    # Return 204 No Content on successful deletion
    return


# --- PUT/Update Specific Image ---
# This replaces the image file and updates the storage URL/object_name in the DB.
@app.put("/images/{image_id}", response_model=ImageRecord)
async def update_image(
    # image_id is now a string (UUID)
    image_id: str = Path(..., description="The UUID of the image to update"),
    file: UploadFile = File(...), # New file to replace the old one
    user_id: str = Depends(get_current_user_id)
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
        # 1. Get the existing image record to verify ownership and get old object name
        old_image_record = get_image_record_by_id(user_id, image_id)
        if old_image_record is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        old_object_name = old_image_record.get("object_name")

        if not old_object_name:
             # Cannot proceed with update if we can't identify the old R2 file to delete later
             print(f"Error: object_name missing for image UUID {image_id} for user {user_id} during update attempt.")
             raise HTTPException(status_code=500, detail="Image record is incomplete (missing object name). Cannot update.")


        # 2. Validate and process the NEW uploaded file (similar to /upload-image/)
        if file.size > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"New file size exceeds the limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.")

        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid new file type. Only images are allowed.")

        temp_file_path = f"temp_update_{uuid.uuid4().hex}_{file.filename}"
        with open(temp_file_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        try:
            img = Image.open(temp_file_path)
            img.verify()
            img.close()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted new image file.")

        if detector:
            try:
                detections = detector.detect(temp_file_path)
                for item in detections:
                    label = item.get("class")
                    score = item.get("score", 0)
                    if label in adult_content_labels and score > 0.2:
                         raise HTTPException(
                              status_code=400,
                              detail=f"Adult content detected in new image: {label} ({score:.2f})"
                         )
            except Exception as e:
                print(f"NudeNet error during update: {e}")
                raise HTTPException(status_code=500, detail="Error during nudity detection for new image.")
        else:
            print("NudeNet detector not initialized. Skipping nudity check for new image.")

        webp_bytes = None
        try:
            image = Image.open(temp_file_path)
            processed_image = crop_image_to_aspect_ratio(image)
            new_webp_bytes = convert_to_webp(processed_image)
            image.close()
            processed_image.close()
        except Exception as e:
            print(f"New image processing error during update: {e}")
            raise HTTPException(status_code=500, detail="Failed to process new image.")

        # 3. Upload the NEW processed image to R2
        new_object_uuid = uuid.uuid4().hex
        # Use user_id in new object name path
        new_object_name = f"uploads/{user_id}/{new_object_uuid}.webp"
        try:
            if new_webp_bytes is None:
                 raise Exception("Processed new image bytes not available for upload.")
            new_r2_url = upload_file_to_r2(new_webp_bytes, new_object_name)
            if not new_r2_url:
                 raise HTTPException(status_code=500, detail="New image uploaded but URL construction failed.")
        except Exception as e:
            print(f"New R2 upload error during update: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload new image to storage.")

        # 4. Update the database record with the new R2 URL and object name
        try:
            # Pass image_id as string (UUID)
            updated_in_db = update_image_record_url_by_id(user_id, image_id, new_r2_url, new_object_name)
            if not updated_in_db:
                 print(f"Warning: DB record UUID {image_id} not found for update for user {user_id}.")
                 # CRITICAL INCONSISTENCY: New file uploaded, but DB record wasn't updated.
                 # Attempt to clean up the NEWLY uploaded R2 file before raising error.
                 try:
                      if new_object_name:
                           delete_file_from_r2(new_object_name)
                           print(f"Cleaned up newly uploaded R2 object {new_object_name} after DB update failure.")
                 except Exception as cleanup_e:
                      print(f"CRITICAL: Failed to clean up newly uploaded R2 object {new_object_name} after DB update failure: {cleanup_e}")
                 # Raise a 404 as the record wasn't found to update (should match initial check)
                 raise HTTPException(status_code=404, detail="Image record not found in database.")
        except Exception as e:
            print(f"DB update error for image UUID {image_id} for user {user_id}: {e}")
            # CRITICAL INCONSISTENCY: New file uploaded, but DB update failed.
            # Attempt cleanup of the NEWLY uploaded R2 file.
            try:
                 if new_object_name:
                      delete_file_from_r2(new_object_name)
                      print(f"Cleaned up newly uploaded R2 object {new_object_name} after DB update exception.")
            except Exception as cleanup_e:
                 print(f"CRITICAL: Failed to clean up newly uploaded R2 object {new_object_name} after DB update exception: {cleanup_e}")
            raise HTTPException(status_code=500, detail="Failed to update image record in database.")


        # 5. Delete the OLD file from R2 storage (best effort, log if fails)
        # We retrieved old_object_name at step 1.
        if old_object_name:
            try:
                # delete_file_from_r2 handles NoSuchKey warnings internally.
                delete_file_from_r2(old_object_name)
                print(f"Successfully deleted old R2 object: {old_object_name}")
            except Exception as e:
                # Log the error but don't fail the entire request
                print(f"Warning: Failed to delete old R2 object {old_object_name} for image UUID {image_id} (user {user_id}): {e}")


        # 6. Success - Return the updated record
        # Fetch the updated record to return the complete, current state.
        updated_record = get_image_record_by_id(user_id, image_id)
        if updated_record is None:
             # This would be a highly unusual state if the update succeeded
             print(f"CRITICAL: Updated record UUID {image_id} not found immediately after update for user {user_id}.")
             raise HTTPException(status_code=500, detail="Failed to retrieve updated image record.")

        return updated_record


    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"An unhandled error occurred during image update for UUID {image_id} (user {user_id}): {e}")
        # Final catch-all cleanup attempt for the NEWLY uploaded file if an unexpected error occurred
        try:
             if new_object_name:
                  delete_file_from_r2(new_object_name)
                  print(f"Cleaned up newly uploaded R2 object {new_object_name} after unexpected update failure.")
        except Exception as cleanup_e:
             print(f"CRITICAL: Failed to clean up newly uploaded R2 object {new_object_name} after unexpected update failure: {cleanup_e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during update.")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


# Optional: Add a shutdown event to close the database pool
@app.on_event("shutdown")
async def shutdown_event():
    if db_pool:
        db_pool.closeall()
        print("PostgreSQL connection pool closed.")


# --- Run the application ---
if __name__ == "__main__":
    ai_models_dir = os.path.join(os.path.dirname(__file__), "ai_models")
    if not os.path.exists(ai_models_dir):
        os.makedirs(ai_models_dir)
        print(f"Created directory: {ai_models_dir}")

    if not os.path.exists(settings.MODEL_PATH):
         print(f"Error: NudeNet model file not found at {settings.MODEL_PATH}. Please download it.")
         print("You can typically download it from the NudeNet repository or instructions.")

    uvicorn.run(app, host="0.0.0.0", port=8083)