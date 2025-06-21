
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Define the list of allowed origins for your application.
# It's good practice to manage this in a central config or from environment variables.
origins = [
    "http://localhost:8081",
    "https://single-identity-service.onrender.com", 
]

def setup_cors(app: FastAPI):
    """
    Configures the Cross-Origin Resource Sharing (CORS) middleware for the application.
    
    Args:
        app (FastAPI): The FastAPI application instance.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,       # List of origins allowed to make requests
        allow_credentials=True,      # Allow cookies to be included in cross-origin requests
        allow_methods=["*"],         # Allow all standard methods (GET, POST, etc.)
        allow_headers=["*"],         # Allow all headers
    )