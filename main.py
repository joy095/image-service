# main.py
import logging
import uvicorn
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import os

# Local imports
from image_router import router as image_router
from cors import setup_cors
from database import db_pool
from user_models import User
from auth import auth_middleware
from image_services import process_and_upload_image
from schemas import UploadResponse

# --- App Initialization ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

os.environ["ONNX_DISABLE_CPUINFO"] = "1"  # Disable ONNX CPU info detection for Leapcell

app = FastAPI(title="Image Service")

# --- CORS Configuration ---
setup_cors(app)

# --- Health Check Endpoints ---
@app.get("/health")
async def health_check():
    return {"message": "ok from image service"}


# All routes from image_router will be available under the app
app.include_router(image_router)


# --- Single Image Upload (can be kept here or moved to router) ---
@app.post("/upload-image/", response_model=UploadResponse, status_code=201, tags=["images"])
async def upload_single_image(
    user: User = Depends(auth_middleware),
    image: UploadFile = File(...)
):
    """Upload a single image."""
    result = await process_and_upload_image(image, str(user.id))
    if not result["success"]:
        # Use details from the service to raise a proper HTTP Exception
        if "not found" in result.get("detail", ""):
            raise HTTPException(status_code=404, detail=result["detail"])
        elif "Invalid" in result.get("detail", "") or "exceeds limit" in result.get("detail", ""):
            raise HTTPException(status_code=400, detail=result["detail"])
        else:
            raise HTTPException(status_code=500, detail=result["detail"])

    return result


# --- Application Lifecycle Events ---
@app.on_event("shutdown")
async def shutdown_event():
    """Close the database connection pool on application shutdown."""
    if db_pool:
        db_pool.closeall()
        logger.info("PostgreSQL connection pool closed.")

# --- Run the application ---
if __name__ == "__main__":
    # You would run this using: uvicorn main:app --host 0.0.0.0 --port 8083 --reload
    uvicorn.run(app, host="0.0.0.0", port=8083)