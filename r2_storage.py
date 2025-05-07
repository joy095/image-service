import boto3
import os
from config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure the boto3 client for Cloudflare R2
try:
    r2_client = boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        # Cloudflare R2 often uses 'auto' or doesn't strictly require a region
        # region_name='auto' # Example region
    )
    logger.info("Cloudflare R2 client initialized.")
except Exception as e:
    logger.error(f"Failed to initialize Cloudflare R2 client: {e}")
    # Handle initialization errors as needed

def upload_file_to_r2(file_object, object_name: str):
    """Uploads a file-like object to Cloudflare R2."""
    try:
        r2_client.upload_fileobj(file_object, settings.R2_BUCKET_NAME, object_name)
        # Construct the public URL
        if settings.R2_PUBLIC_URL_BASE:
             r2_url = f"{settings.R2_PUBLIC_URL_BASE}/{object_name}"
        else:
             # Fallback or error if public URL base is not configured
             logger.warning("R2_PUBLIC_URL_BASE not set. Cannot construct public URL.")
             r2_url = f"r2://{settings.R2_BUCKET_NAME}/{object_name}" # Internal identifier format
        logger.info(f"Uploaded {object_name} to R2. URL: {r2_url}")
        return r2_url
    except Exception as e:
        logger.error(f"Failed to upload {object_name} to R2: {e}")
        raise # Re-raise the exception