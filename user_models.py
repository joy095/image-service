from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from psycopg2 import pool
import logging
from database import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)

# Pydantic model for User
class User(BaseModel):
    id: UUID
    username: str
    token_version: int
    email: Optional[str] = None  # Add if needed for email verification
    is_verified_email: Optional[bool] = False  # Add if needed for verification status

    model_config = {
        "from_attributes": True
    }
        

def get_user_by_id(user_id: str) -> Optional[User]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT id, username, token_version, email, is_verified_email
            FROM users
            WHERE id = %s
        """
        cursor.execute(query, (str(user_id),))  # Convert UUID to string
        row = cursor.fetchone()

        if row:
            user_data = {
                "id": row[0],
                "username": row[1],
                "token_version": row[2],
                "email": row[3],
                "is_verified_email": row[4],
            }
            return User(**user_data)

        return None
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        raise
    finally:
        release_db_connection(conn)

