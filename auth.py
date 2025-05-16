import logging
from typing import Optional

from fastapi import Depends, HTTPException, status, Header # Import Header
from jose import JWTError, jwt # Using python-jose library

from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

# --- Dependency to get the current user ID from the JWT ---
# Removed dependency on OAuth2BearerToken
async def get_current_user_id(authorization: str = Header(None)) -> str:
   
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
       
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info(f"JWT payload decoded: {payload}")

     
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

