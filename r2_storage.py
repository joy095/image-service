# r2_storage.py
import boto3
from config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure the boto3 client for Cloudflare R2
r2_client = None # Initialize as None
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
    # This might be a critical failure depending on app logic
    # You might want to add logic here to prevent the app from starting or
    # gracefully handle storage unavailability.

def upload_file_to_r2(file_object, object_name: str):
    """Uploads a file-like object to Cloudflare R2."""
    if r2_client is None:
        logger.error("R2 client not initialized. Cannot upload.")
        raise ConnectionError("R2 storage is not available.") # Or a custom exception

    try:
        r2_client.upload_fileobj(file_object, settings.R2_BUCKET_NAME, object_name)
        # Construct the public URL
        if settings.R2_PUBLIC_URL_BASE:
             # Ensure trailing slash on base URL if needed
             base_url = settings.R2_PUBLIC_URL_BASE.rstrip('/')
             r2_url = f"{base_url}/{object_name}"
        else:
             # Fallback or error if public URL base is not configured
             logger.warning("R2_PUBLIC_URL_BASE not set. Cannot construct public URL.")
             # This might be acceptable if the URL isn't needed immediately,
             # but for GET routes, you'll need it.
             r2_url = f"r2://{settings.R2_BUCKET_NAME}/{object_name}" # Internal identifier format
        logger.info(f"Uploaded {object_name} to R2. URL: {r2_url}")
        return r2_url
    except Exception as e:
        logger.error(f"Failed to upload {object_name} to R2: {e}")
        raise # Re-raise the exception

def delete_file_from_r2(object_name: str) -> bool:
    """Deletes an object from Cloudflare R2."""
    if r2_client is None:
        logger.error("R2 client not initialized. Cannot delete.")
        # Decide how to handle this - maybe proceed with DB deletion if R2 delete isn't critical?
        # For now, let's raise an error as deleting from storage is usually coupled with DB.
        raise ConnectionError("R2 storage is not available.")

    try:
        r2_client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=object_name)
        logger.info(f"Deleted {object_name} from R2.")
        return True
    except r2_client.exceptions.ClientError as e:
        # Handle specific S3/R2 errors, e.g., object not found
        if e.response['Error']['Code'] == 'NoSuchKey':
             logger.warning(f"Attempted to delete non-existent R2 object: {object_name}")
             return False # Indicate object wasn't there
        else:
             logger.error(f"Failed to delete {object_name} from R2: {e}")
             raise # Re-raise other client errors
    except Exception as e:
        logger.error(f"An unexpected error occurred while deleting {object_name} from R2: {e}")
        raise # Re-raise other exceptions