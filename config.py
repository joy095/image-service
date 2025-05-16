import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

class Settings:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "fallback-secret-key") # Fallback is just for development, use .env
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    DATABASE_URL: str = os.getenv("DATABASE_URL")


    R2_ENDPOINT_URL: str = os.getenv("R2_ENDPOINT_URL")
    R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID")
    R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY")
    R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME")
    R2_PUBLIC_URL_BASE: str = os.getenv("R2_PUBLIC_URL_BASE")

    MODEL_PATH: str = os.getenv("MODEL_PATH", os.path.join(os.path.dirname(__file__), "ai_models/640m.onnx"))

    # Image processing settings
    CROPPED_ASPECT_RATIO: float = 1.0 # Example: 1.0 for a square (1:1)

settings = Settings()