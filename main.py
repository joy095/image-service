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
        # Initialize the detector with the model path and inference resolution
        detector = NudeDetector(model_path=model_path, inference_resolution=640)
        print("NudeNet detector initialized successfully.")
    except Exception as e:
        print(f"ERROR: Failed to initialize NudeNet detector: {e}")
        print("Nudity detection will be skipped.")
        detector = None # Ensure detector is None on failure


# List of adult content labels to check for (based on NudeNet output)
adult_content_labels = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_BREAST_AREOLA", # Added more specific labels
    "FEMALE_GENITALIA", "MALE_GENITALIA"
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
# This endpoint does NOT require JWT authentication and is separate from the upload process.
# It performs the *same* nudity check logic as the upload route, but is a standalone endpoint.
@app.post("/detect-nudity/")
async def detect_nudity(file: UploadFile = File(...)):
    """Checks an image for adult content using NudeNet."""
    temp_file_path = f"temp_detect_{uuid.uuid4().hex}_{file.filename}" # Use uuid for uniqueness
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
             print("NudeNet detector not available in /detect-nudity/. Skipping nudity detection.")


        return JSONResponse(content={"is_adult_content": is_adult}, status_code=200)

    except Exception as e:
        print(f"Error during nudity detection in /detect-nudity/: {e}")
        return JSONResponse(content={"is_adult_content": False, "detail": "Internal server error."}, status_code=500)
    finally:
        # Ensure temporary file is removed
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

# --- New Image Upload Endpoint (Requires JWT Authentication) ---
@app.post("/upload-image/")
async def upload_image(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id)
):
    """
    Upload an image, detect nudity, process (crop + webp), upload to R2, save link to DB.
    """
    temp_file_path = f"temp_{uuid.uuid4().hex}_{file.filename}"
    try:
        # 1. Validate file type
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

        # 2. Save uploaded file temporarily
        with open(temp_file_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        # 3. Verify it's a valid image
        try:
            Image.open(temp_file_path).verify()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted image file.")

        # 4. Nudity detection (block upload if adult content found)
        # 4. Nudity detection (block upload if adult content found)
        if detector:
            try:
                detections = detector.detect(temp_file_path)
                print("Detections:", detections)  # Optional: for debugging

                for item in detections:
                    label = item.get("class")
                    score = item.get("score", 0)

                    if label in adult_content_labels and score > 0.2:
                        print(f"Adult content detected: {label} ({score})")
                        # Immediately return with HTTP 400
                        return JSONResponse(
                            status_code=400,
                            content={"detail": f"Adult content detected: {label} ({score:.2f})"}
                        )
            except Exception as e:
                print(f"NudeNet error: {e}")
                raise HTTPException(status_code=500, detail="Error during nudity detection.")
        else:
            print("NudeNet detector not initialized. Skipping nudity check.")


        # 5. Image processing (crop + convert to webp)
        try:
            image = Image.open(temp_file_path)
            cropped = crop_image_to_aspect_ratio(image, settings.CROPPED_ASPECT_RATIO)
            webp_bytes = convert_to_webp(cropped)
            image.close()
            cropped.close()
        except Exception as e:
            print(f"Image processing error: {e}")
            raise HTTPException(status_code=500, detail="Failed to process image.")

        # 6. Upload to R2
        try:
            r2_path = f"uploads/{user_id}/{uuid.uuid4().hex}.webp"
            r2_url = upload_file_to_r2(webp_bytes, r2_path)
            if not r2_url:
                raise HTTPException(status_code=500, detail="Image uploaded but URL construction failed.")
        except Exception as e:
            print(f"R2 upload error: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload image to storage.")

        # 7. Save to DB
        try:
            save_image_record(user_id=user_id, r2_url=r2_url)
        except Exception as e:
            print(f"DB save error: {e}")
            raise HTTPException(status_code=500, detail="Failed to save image info to database.")

        # 8. Success
        return JSONResponse(content={"message": "Upload successful", "r2_url": r2_url}, status_code=201)

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
