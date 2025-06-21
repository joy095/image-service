import os
from dotenv import load_dotenv
import base64

load_dotenv()  # Load environment variables from .env file


def must_getenv(key: str, allow_empty: bool = False) -> str:
    value = os.getenv(key)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    if not allow_empty and value.strip() == "":
        raise EnvironmentError(f"Environment variable {key} is empty.")
    return value


class Settings:
    # Strict required variables
    SECRET_KEY: bytes = base64.b64decode(must_getenv("SECRET_KEY"))
    ALGORITHM: str = must_getenv("ALGORITHM")

    DATABASE_URL: str = must_getenv("DATABASE_URL")

    R2_ENDPOINT_URL: str = must_getenv("R2_ENDPOINT_URL")
    R2_ACCESS_KEY_ID: str = must_getenv("R2_ACCESS_KEY_ID")
    R2_SECRET_ACCESS_KEY: str = must_getenv("R2_SECRET_ACCESS_KEY")
    R2_BUCKET_NAME: str = must_getenv("R2_BUCKET_NAME")
    R2_PUBLIC_URL_BASE: str = must_getenv("R2_PUBLIC_URL_BASE")

    # Optional or fallback values
    MODEL_PATH: str = os.getenv(
        "MODEL_PATH",
        os.path.join(os.path.dirname(__file__), "ai_models/640m.onnx")
    )

    # Constants / Defaults
    CROPPED_ASPECT_RATIO: float = 1.0  # Example: 1.0 for square (1:1)


settings = Settings()
