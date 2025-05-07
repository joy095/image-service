import logging
# Removed os import as it wasn't used in the provided code snippet, but keep if needed elsewhere
# import os
import psycopg2
from psycopg2 import pool # Correct import for pool
from config import settings
# Removed sys import as it wasn't used in the provided code snippet, but keep if needed elsewhere
# import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Basic connection pool setup
# db_pool is defined here at the module level, making it importable
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
    # Depending on your application, you might want to exit or handle this differently
    # sys.exit(1) # Uncomment if failure to connect is fatal

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
    if conn and db_pool: # Check if conn and db_pool are valid
        try:
            db_pool.putconn(conn)
        except Exception as e:
            logger.error(f"Failed to release connection to pool: {e}")
            # Handle error releasing connection if necessary

def save_image_record(user_id: str, r2_url: str): # Changed user_id to str based on JWT
    """Saves the image URL to the database."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Assumes you have a table named 'images' with columns user_id, r2_url
        # Using sql.SQL for safer query construction is recommended, but using %s is also common
        cursor.execute(
            "INSERT INTO images (user_id, r2_url) VALUES (%s, %s)",
            (user_id, r2_url) # Pass user_id as string if that's its type from JWT
        )
        conn.commit()
        logger.info(f"Saved image URL for user {user_id}: {r2_url}")
    except Exception as e:
        logger.error(f"Database error saving image record for user {user_id}: {e}")
        if conn:
            conn.rollback() # Rollback in case of error
        raise # Re-raise the exception
    finally:
        release_db_connection(conn)

# You might want to add an event listener in main.py to close the pool on shutdown
# @app.on_event("shutdown")
# async def shutdown_event():
#     if database.db_pool:
#         database.db_pool.closeall()
#         logger.info("PostgreSQL connection pool closed.")

