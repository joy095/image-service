import logging
from typing import Optional

from fastapi import Depends, HTTPException, status, Header # Import Header
from jose import JWTError, jwt # Using python-jose library

# Import your settings object
# This assumes you have a config.py or settings.py file
# where you define your settings, likely loading from environment variables.
# Make sure 'config' is the correct module name if your file is named differently.
from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration loaded from settings ---
# Load the secret key and algorithm from the settings object
# These should be defined in your config.py using os.getenv or pydantic_settings
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

# --- Dependency to get the current user ID from the JWT ---
# Removed dependency on OAuth2BearerToken
async def get_current_user_id(authorization: str = Header(None)) -> str:
    """
    Dependency function to validate the JWT token from the Authorization header
    and extract the user_id.

    Args:
        authorization: The full Authorization header string (e.g., "Bearer <token>").
                       FastAPI injects this automatically using Header().

    Returns:
        The user_id (as a string) from the JWT payload if the token is valid.

    Raises:
        HTTPException: If the Authorization header is missing/invalid,
                       the token is invalid/expired, or the user_id is missing
                       in the payload.
    """
    logger.info("Attempting to validate JWT token from Authorization header.")

    # Check if the Authorization header is present and in the correct format
    if not authorization or not authorization.startswith("Bearer "):
        logger.error("Authorization header missing or not in 'Bearer <token>' format.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract the token string
    token = authorization.split(" ")[1]
    logger.info(f"Extracted token: {token[:10]}...") # Log first few chars

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the JWT token
        # The payload is the dictionary inside the token
        # jwt.decode automatically checks for expiry by default
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info(f"JWT payload decoded: {payload}")

        # Extract the user_id from the payload
        # Based on your example payload, the user ID is under the 'user_id' key.
        user_id: str = payload.get("user_id")

        if user_id is None:
            logger.error("user_id not found in JWT payload.")
            # If user_id is missing in the token payload, it's an invalid token for this service
            raise credentials_exception

        # You could add more checks here if needed, e.g., check 'iss' for issuer

        logger.info(f"Successfully validated JWT. Extracted user_id: {user_id}")
        return user_id

    except JWTError as e:
        # This catches various JWT errors like invalid signature, expired token, etc.
        logger.error(f"JWT validation failed: {e}")
        raise credentials_exception
    except Exception as e:
        # Catch any other unexpected errors during the process
        logger.error(f"An unexpected error occurred during JWT processing: {e}")
        # Return a 500 error for unexpected server-side issues
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during authentication",
        )

