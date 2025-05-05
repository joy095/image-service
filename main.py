from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from nudenet import NudeDetector
import shutil
import os
from PIL import Image

app = FastAPI()

# Define the model path
model_path = os.path.join(os.path.dirname(__file__), "ai_models/640m.onnx")

# Check if the model file exists, and initialize the detector if it does
if not os.path.exists(model_path):
    raise FileNotFoundError(f"Model file not found at {model_path}")
else:
    detector = NudeDetector(model_path=model_path, inference_resolution=640)

# List of adult content labels to check for
adult_content_labels = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED"
]

@app.get("/health")
async def health_check():
    return {"message": "ok from image check service"}

@app.head("/")
async def head():
    return JSONResponse(content={}, status_code=200)

@app.get("/", response_class=HTMLResponse)
async def main():
    return """
    <html>
        <head>
            <title>Upload Image</title>
        </head>
        <body>
            <h2>Upload an image to check for nudity:</h2>
            <form action="/detect-nudity/" enctype="multipart/form-data" method="post">
                <input name="file" type="file" accept="image/*" required>
                <input type="submit" value="Upload">
            </form>
        </body>
    </html>
    """

@app.post("/detect-nudity/")
async def detect_nudity(file: UploadFile = File(...)):
    temp_file_path = f"temp_{file.filename}"
    try:
        # Validate the file type
        if not file.content_type.startswith("image/"):
            return JSONResponse(content={"error": "Uploaded file is not an image."}, status_code=400)

        # Save the uploaded file temporarily
        with open(temp_file_path, "wb") as temp_file:
            shutil.copyfileobj(file.file, temp_file)

        # Verify the image file
        try:
            Image.open(temp_file_path).verify()
        except Exception:
            os.remove(temp_file_path)
            return JSONResponse(content={"error": "Uploaded file is not a valid image."}, status_code=400)

        # Classify the image using the full-size NudeNet detector
        result = detector.detect(temp_file_path)

        # Print the result to debug and inspect its structure
        print(result)

        # Check for adult content labels in the result
        if isinstance(result, list):  # Check if the result is a list of classifications
            for item in result:
                # Ensure the class and score exist in the item
                if "class" in item and "score" in item:
                    # Check if the class is in the adult_content_labels and the score is above threshold
                    if item["class"] in adult_content_labels and item["score"] > 0.5:
                        os.remove(temp_file_path)
                        return JSONResponse(content={"error": "Adult content detected in the image."}, status_code=400)

        # Clean up the temporary file
        os.remove(temp_file_path)

        return {
            "filename": file.filename,
            "full_classification": result
        }

    except Exception as e:
        # Handle any unexpected errors
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return JSONResponse(content={"error": f"An unexpected error occurred: {str(e)}"}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8083)  # Specify port here