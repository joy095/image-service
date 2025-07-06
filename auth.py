import logging
import json
from typing import Optional
from fastapi import Request, HTTPException, status, Depends
from jose import jwt, JWTError
from pydantic import BaseModel, Field
from config import settings
from user_models import get_user_by_id, User
# from user_models import get_user_by_id, is_email_verified, User
from fastapi.responses import JSONResponse

logger = logging.getLogger("auth")
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM


class BodyData(BaseModel):
    user_id: Optional[str] = Field(None, alias="user_id")


async def auth_middleware(request: Request) -> User:
    logger.info("=== AuthMiddleware START ===")

    # 1. Read access_token from cookies
    token_string = request.cookies.get("access_token")
    if not token_string:
        logger.error("Missing or empty access_token cookie - ABORTING")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Unauthorized: No token provided"},
        )

    # 2. Decode and validate JWT
    try:
        payload = jwt.decode(token_string, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info("JWT decoded successfully")
    except JWTError as e:
        logger.error(f"Invalid JWT: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid or expired token"},
        )

    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Missing user_id in JWT")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid token claims"},
        )

    token_version = payload.get("token_version")
    if token_version is None:
        logger.error("Missing token_version in JWT")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Missing token version"},
        )

    try:
        token_version = int(token_version)
    except Exception:
        logger.error("Invalid token_version format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid token version format"},
        )

    # 3. Fetch user and compare token version
    user = get_user_by_id(user_id)
    if not user:
        logger.error(f"User not found: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "User not found"},
        )

    if user.token_version != token_version:
        logger.error("Token version mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Session expired. Please log in again."},
        )

    # 4. Optional: Check email verified
    # if not is_email_verified(user.id):
    #     logger.error(f"Email not verified for user: {user.id}")
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail={"error": "Email not verified"},
    #     )

    # 5. Optional: Validate user_id in body
    try:
        body_bytes = await request.body()
        request._receive = lambda: {"type": "http.request", "body": body_bytes}
        if body_bytes:
            parsed = BodyData.parse_raw(body_bytes)
            if parsed.user_id and str(user.id) != parsed.user_id:
                logger.error("User ID in body does not match token")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": "Mismatched user ID in body"},
                )
    except json.JSONDecodeError:
        logger.warning("Invalid JSON body. Skipping body user_id check.")
    except Exception as e:
        logger.warning(f"Unexpected body parsing error: {e}")

    logger.info(f"=== AuthMiddleware SUCCESS - User {user.id} authenticated ===")
    return user
