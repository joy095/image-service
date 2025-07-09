# async_utils.py
import asyncio

# --- Helper functions to run synchronous (blocking) code in a separate thread ---
# These functions use asyncio.to_thread to prevent blocking the event loop.

async def run_blocking_io(func, *args, **kwargs):
    """
    Generic function to run any blocking I/O operation in a separate thread.
    This includes Pillow, NudeNet, R2 storage, database calls, and file system operations.
    """
    return await asyncio.to_thread(func, *args, **kwargs)