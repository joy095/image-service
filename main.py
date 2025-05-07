from fastapi import FastAPI, File, UploadFile, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from nudenet import NudeDetector
import shutil
import os
from PIL import Image
import uvicorn
import uuid # To generate unique filenames
import io # To work with image data in memory

# Import your configuration and other modules
from config import settings
# Import the JWT authentication dependency
from auth import get_current_user_id
from database import save_image_record, db_pool # Import db_pool to close on shutdown
from r2_storage import upload_file_to_r2
from image_utils import crop_image_to_aspect_ratio, convert_to_webp

app = FastAPI()

# --- NudeNet Detector Initialization (from your original code) ---
# Define the model path from settings
model_path = settings.MODEL_PATH

# Check if the model file exists, and initialize the detector if it does
detector = None # Initialize as None
if not os.path.exists(model_path):
    print(f"WARNING: NudeNet model file not found at {model_path}. Nudity detection will be skipped.")
    # Consider raising an exception here if nudity detection is mandatory
else:
    try:
        detector = NudeDetector(model_path=model_path, inference_resolution=640)
        print("NudeNet detector initialized successfully.")
    except Exception as e:
        print(f"ERROR: Failed to initialize NudeNet detector: {e}")
        print("Nudity detection will be skipped.")
        detector = None # Ensure detector is None on failure


# List of adult content labels to check for
adult_content_labels = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED"
]

# --- Health Check Endpoints (from your original code) ---
@app.get("/health")
async def health_check():
    return {"message": "ok from image service"}

@app.head("/health")
async def head():
    return JSONResponse(content={}, status_code=200)

@app.get("/", response_class=HTMLResponse)
async def main_form():
    # Simplified form for testing, token handling requires client-side JS or a different flow
    return """
    <html>
        <head><title>Upload Image with Auth & Processing</title></head>
        <body>
            <h2>Upload an image:</h2>
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
        </body>
    </html>
    """

# --- Original Nudity Detection Endpoint (Optional - keep or remove) ---
# This endpoint does NOT require JWT authentication
@app.post("/detect-nudity/")
async def detect_nudity(file: UploadFile = File(...)):
    """Checks an image for adult content using NudeNet."""
    temp_file_path = f"temp_{uuid.uuid4().hex}_{file.filename}" # Use uuid for uniqueness
    is_adult = False
    try:
        # Validate the file type
        if not file.content_type or not file.content_type.startswith("image/"):
             return JSONResponse(content={"is_adult_content": False, "detail": "Invalid file type."}, status_code=400)

        # Save the uploaded file temporarily
        with open(temp_file_path, "wb") as temp_file:
             shutil.copyfileobj(file.file, temp_file)

        # Verify the image file is valid
        try:
             Image.open(temp_file_path).verify()
             # Re-open as verify closes the file
             img = Image.open(temp_file_path)
             img.close() # Close immediately after verification
        except Exception:
            # Use 400 Bad Request for invalid image file
            return JSONResponse(content={"is_adult_content": False, "detail": "Invalid image file."}, status_code=400)

        # Classify the image using NudeNet if detector is initialized
        if detector:
            result = detector.detect(temp_file_path)

            # Check for adult content
            for item in result:
                # Threshold check (e.g., confidence > 20%)
                if item.get("class") in adult_content_labels and item.get("score", 0) > 0.2:
                    is_adult = True
                    break # Found adult content, no need to check further
        else:
             print("NudeNet detector not available. Skipping nudity detection.")


        return JSONResponse(content={"is_adult_content": is_adult}, status_code=200)

    except Exception as e:
        print(f"Error during nudity detection: {e}")
        return JSONResponse(content={"is_adult_content": False, "detail": "Internal server error."}, status_code=500)
    finally:
        # Ensure temporary file is removed
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

# --- New Image Upload Endpoint (Requires JWT Authentication) ---
@app.post("/upload-image/")
async def upload_image(
    file: UploadFile = File(...),
    # This is where the get_current_user_id dependency is used.
    # FastAPI will call get_current_user_id before running this function.
    # If get_current_user_id succeeds, its return value (the user_id string)
    # is passed into the 'user_id' parameter of this function.
    # If get_current_user_id raises an HTTPException (like 401), this function
    # will not be called, and FastAPI will return the HTTPException response.
    user_id: str = Depends(get_current_user_id)
):
    """
    Uploads an image, checks for nudity, processes it (crop, webp),
    uploads to R2, and saves the link to the database.
    Requires a valid JWT in the Authorization: Bearer header.
    The user_id from the JWT will be available in the user_id parameter.
    """
    temp_file_path = None # Initialize outside try block
    try:
        # 1. Validate file type
        if not file.content_type or not file.content_type.startswith("image/"):
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file type. Only images are allowed.")

        # 2. Save file temporarily for processing (NudeNet and Pillow might need a file path)
        # Ensure the temp directory exists if not saving in current dir
        temp_file_path = f"temp_{uuid.uuid4().hex}_{file.filename}"
        with open(temp_file_path, "wb") as temp_file:
            shutil.copyfileobj(file.file, temp_file)

        # 3. Verify image file is valid
        try:
            img = Image.open(temp_file_path)
            img.verify() # Verify the image file format is valid
            img.close() # Close after verification
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or corrupted image file.")

        # 4. Check for adult content using NudeNet (if detector is available)
        if detector:
            try:
                detection_result = detector.detect(temp_file_path)
                for item in detection_result:
                    if item.get("class") in adult_content_labels and item.get("score", 0) > 0.2:
                        # If adult content is detected above threshold
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Adult content detected in the image."
                        )
            except Exception as e:
                 # Log the error but maybe don't block the upload unless critical
                 print(f"Error during NudeNet detection: {e}")
                 # Depending on policy, you might still want to block on detector error
                 # raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error during nudity detection.")

        else:
             print("NudeNet detector not available. Skipping nudity detection for upload.")


        # 5. Image Processing (Crop and Convert to WebP)
        try:
            original_image = Image.open(temp_file_path)
            cropped_image = crop_image_to_aspect_ratio(original_image, settings.CROPPED_ASPECT_RATIO)
            webp_image_bytes = convert_to_webp(cropped_image)
            original_image.close() # Close original PIL image
            cropped_image.close() # Close cropped PIL image
        except Exception as e:
             print(f"Error during image processing: {e}")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process image.")

        # 6. Upload to Cloudflare R2
        try:
            # Generate a unique filename for R2, using the user_id in the path
            r2_object_name = f"uploads/{user_id}/{uuid.uuid4().hex}.webp"
            r2_url = upload_file_to_r2(webp_image_bytes, r2_object_name)
            if not r2_url:
                 # Handle case where public URL base isn't configured
                 raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="R2 upload successful, but public URL could not be constructed.")
        except Exception as e:
             print(f"Error during R2 upload: {e}")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to upload image to storage.")


        # 7. Save link to PostgreSQL database
        try:
            # Pass the extracted user_id to the database function
            save_image_record(user_id=user_id, r2_url=r2_url)
        except Exception as e:
             print(f"Error saving R2 URL to database: {e}")
             # Consider if you should roll back the R2 upload here or just log the DB error
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save image information to database.")

        # 8. Return success response
        return JSONResponse(
            content={"message": "Image uploaded and processed successfully", "r2_url": r2_url},
            status_code=status.HTTP_201_CREATED # Use 201 Created for successful resource creation
        )

    except HTTPException as http_exc:
        # Re-raise FastAPI HTTPExceptions
        raise http_exc
    except Exception as e:
        # Catch any other unexpected errors
        print(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")
    finally:
        # Ensure temporary file is removed
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            print(f"Cleaned up temp file: {temp_file_path}")

# Optional: Add a shutdown event to close the database pool
@app.on_event("shutdown")
async def shutdown_event():
    if db_pool:
        db_pool.closeall()
        print("PostgreSQL connection pool closed.")


# --- Run the application ---
if __name__ == "__main__":
    # Ensure the AI models directory exists
    ai_models_dir = os.path.join(os.path.dirname(__file__), "ai_models")
    if not os.path.exists(ai_models_dir):
        os.makedirs(ai_models_dir)
        print(f"Created directory: {ai_models_dir}")

    # Ensure the NudeNet model file is in the ai_models directory or specified path
    if not os.path.exists(settings.MODEL_PATH):
         print(f"Error: NudeNet model file not found at {settings.MODEL_PATH}. Please download it.")
         print("You can typically download it from the NudeNet repository or instructions.")
         # Example (may need adjustment based on NudeNet version/repo):
         # print("Try downloading it manually and placing it in the ai_models directory.")
         # You might also consider adding a script or instructions to download it automatically.

    uvicorn.run(app, host="0.0.0.0", port=8083)
