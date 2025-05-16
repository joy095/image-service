# database.py
import logging
import psycopg2
from psycopg2 import pool
from psycopg2 import sql
from typing import List, Dict, Optional
import datetime # Import datetime for type hinting uploaded_at

from config import settings


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


db_pool = None # Initialize to None before the try block

try:
    db_pool = pool.SimpleConnectionPool(
        1,  # minconn
        10, # maxconn
        settings.DATABASE_URL
    )
    logger.info("PostgreSQL connection pool created successfully.")
except Exception as e:
    logger.error(f"Failed to create PostgreSQL connection pool: {e}")
    # Depending on criticality, you might want to exit here or have a robust retry mechanism

def get_db_connection():
    """Gets a connection from the pool."""
    if db_pool is None:
        logger.error("Database pool is not initialized.")
        raise Exception("Database connection pool not available.")
    try:
        return db_pool.getconn()
    except Exception as e:
        logger.error(f"Failed to get connection from pool: {e}")
        raise

def release_db_connection(conn):
    """Releases a connection back to the pool."""
    if conn and db_pool:
        try:
            if conn.closed == 0 and not conn.get_transaction_status():
                 db_pool.putconn(conn)
            else:
                 conn.close()
                 logger.warning("Discarded a database connection due to open transaction or bad state.")
        except Exception as e:
            logger.error(f"Failed to release connection to pool: {e}")


def save_image_record(user_id: str, r2_url: str, object_name: str) -> Optional[str]: # Return Optional[str] for UUID
    """Saves the image URL, object name, and timestamp to the database and returns the new record UUID."""
    conn = None
    image_uuid = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Assumes table has id (UUID), user_id, r2_url, object_name, uploaded_at
        # Use NOW() for uploaded_at directly in the SQL for simplicity
        query = sql.SQL("INSERT INTO images (user_id, r2_url, object_name, uploaded_at) VALUES (%s, %s, %s, NOW()) RETURNING id")
        cursor.execute(query, (user_id, r2_url, object_name))
        image_uuid = str(cursor.fetchone()[0]) # Get the returned UUID and convert to string
        conn.commit()
        logger.info(f"Saved image record (UUID: {image_uuid}) for user {user_id}: {r2_url}")
        return image_uuid
    except Exception as e:
        logger.error(f"Database error saving image record for user {user_id}: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        release_db_connection(conn)

# Define a structure to match the columns you're selecting
# This helps keep track of the tuple structure returned by fetchone/fetchall
IMAGE_RECORD_COLUMNS = ["id", "user_id", "r2_url", "object_name", "uploaded_at"]

def get_image_record_by_id(user_id: str, image_id: str) -> Optional[Dict]: # image_id is now str (UUID)
    """Gets a single image record by UUID for a specific user."""
    conn = None
    record = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Select all expected columns
        query = sql.SQL("SELECT id, user_id, r2_url, object_name, uploaded_at FROM images WHERE id = %s AND user_id = %s")
        # Ensure image_id is passed as a string (UUID)
        cursor.execute(query, (image_id, user_id))
        record = cursor.fetchone()
        if record:
            # Convert tuple to dictionary using defined column names
            record_dict = dict(zip(IMAGE_RECORD_COLUMNS, record))
            # Ensure UUID is returned as string
            record_dict["id"] = str(record_dict["id"])
            logger.debug(f"Retrieved image record UUID {image_id} for user {user_id}")
            return record_dict
        else:
            logger.debug(f"Image record UUID {image_id} not found for user {user_id}")
            return None
    except Exception as e:
        logger.error(f"Database error retrieving image record UUID {image_id} for user {user_id}: {e}")
        raise
    finally:
        release_db_connection(conn)

def get_all_image_records_by_user_id(user_id: str) -> List[Dict]:
    """Gets all image records for a specific user."""
    conn = None
    records = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Select all expected columns, order by uploaded_at descending
        query = sql.SQL("SELECT id, user_id, r2_url, object_name, uploaded_at FROM images WHERE user_id = %s ORDER BY uploaded_at DESC")
        cursor.execute(query, (user_id,))
        records_tuple = cursor.fetchall()
        # Convert list of tuples to list of dictionaries
        records = [
             dict(zip(IMAGE_RECORD_COLUMNS, rec)) for rec in records_tuple
        ]
        # Ensure UUIDs are strings
        for rec in records:
            rec["id"] = str(rec["id"])

        logger.debug(f"Retrieved {len(records)} image records for user {user_id}")
        return records
    except Exception as e:
        logger.error(f"Database error retrieving all image records for user {user_id}: {e}")
        raise
    finally:
        release_db_connection(conn)

def delete_image_record_by_id(user_id: str, image_id: str) -> bool: # image_id is now str (UUID)
    """Deletes an image record by UUID for a specific user."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = sql.SQL("DELETE FROM images WHERE id = %s AND user_id = %s")
        # Ensure image_id is passed as string
        cursor.execute(query, (image_id, user_id))
        conn.commit()
        rows_deleted = cursor.rowcount
        if rows_deleted > 0:
            logger.info(f"Deleted image record UUID {image_id} for user {user_id}")
            return True
        else:
            logger.debug(f"No image record found to delete with UUID {image_id} for user {user_id}")
            return False
    except Exception as e:
        logger.error(f"Database error deleting image record UUID {image_id} for user {user_id}: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        release_db_connection(conn)

def update_image_record_url_by_id(user_id: str, image_id: str, new_r2_url: str, new_object_name: str) -> bool: # image_id is now str (UUID)
     """Updates the R2 URL and object name for an image record for a specific user."""
     conn = None
     try:
         conn = get_db_connection()
         cursor = conn.cursor()
         # Update r2_url and object_name
         query = sql.SQL("UPDATE images SET r2_url = %s, object_name = %s WHERE id = %s AND user_id = %s")
         # Ensure image_id is passed as string
         cursor.execute(query, (new_r2_url, new_object_name, image_id, user_id))
         conn.commit()
         rows_updated = cursor.rowcount
         if rows_updated > 0:
             logger.info(f"Updated image record UUID {image_id} for user {user_id} with new URL {new_r2_url}")
             return True
         else:
             logger.debug(f"No image record found to update with UUID {image_id} for user {user_id}")
             return False
     except Exception as e:
         logger.error(f"Database error updating image record UUID {image_id} for user {user_id}: {e}")
         if conn:
             conn.rollback()
         raise
     finally:
         release_db_connection(conn)

# Note: The r2_storage.py does not need changes related to the DB schema.