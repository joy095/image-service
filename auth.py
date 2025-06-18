import logging
import json
from typing import Optional
from fastapi import Request, HTTPException, status, Header
from jose import jwt, JWTError
from pydantic import BaseModel, Field
from config import settings
from user_models import get_user_by_id, User

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auth")

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM


class BodyData(BaseModel):
    user_id: Optional[str] = Field(None, alias="user_id")


async def auth_middleware(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> User:
    logger.info("=== AuthMiddleware START ===")

    # 1. Parse Authorization Header
    if not authorization or not authorization.lower().startswith("bearer "):
        logger.error("Authorization header missing or invalid format.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "NO_TOKEN", "error": "No authorization token provided."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = authorization[7:]

    # 2. Decode JWT
    try:
        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info("JWT payload decoded successfully.")
    except JWTError as e:
        logger.error(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "error": f"Could not validate credentials: {e}"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    if not user_id:
        logger.error("Missing user_id in JWT.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "error": "Missing user_id from token."},
        )

    token_version = payload.get("token_version")
    if token_version is None:
        logger.error("Missing token_version in JWT.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "error": "Missing token_version from token."},
        )

    try:
        token_version = int(token_version)
    except (ValueError, TypeError):
        logger.error("Invalid token_version format in JWT.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "error": "Invalid token_version format."},
        )

    # 3. Fetch User from DB
    user = get_user_by_id(user_id)
    if not user:
        logger.error(f"User not found: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "error": "User associated with token not found."},
        )

    # 4. Check token version match
    if user.token_version != token_version:
        logger.error("Token version mismatch.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Session expired. Please log in again."},
        )

    # 5. Check email verification
    if not user.is_verified_email:
        logger.error("Email not verified.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "EMAIL_NOT_VERIFIED", "error": "Email not verified."},
        )

    # 6. Optional: Validate user_id in body (if available)
    try:
        body_bytes = await request.body()
        # Reconstruct request stream for downstream handlers
        request._receive = lambda: {"type": "http.request", "body": body_bytes}
        if body_bytes:
            body_data = json.loads(body_bytes)
            parsed = BodyData(**body_data)
            if parsed.user_id and str(user.id) != parsed.user_id:
                logger.error("User ID in body does not match token.")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "ACCESS_DENIED", "error": "Mismatched user ID in body."},
                )
    except json.JSONDecodeError:
        logger.warning("Request body is not JSON or unreadable. Skipping body user_id check.")
    except Exception as e:
        logger.warning(f"Unexpected error during body parsing: {e}")

    logger.info(f"=== AuthMiddleware SUCCESS - User {user.id} authenticated ===")
    return user
