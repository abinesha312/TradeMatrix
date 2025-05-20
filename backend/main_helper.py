"""
Helper module to run the FastAPI app from the project root
To use: python -m backend.main_helper
"""
import sys
import os
from pathlib import Path

# Get the project root directory
project_root = Path(__file__).parent.parent.absolute()

# Add backend directory to Python path
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if __name__ == "__main__":
    # Import uvicorn here
    import uvicorn
    
    print(f"📂 Added backend directory to Python path: {backend_dir}")
    print(f"🚀 Starting FastAPI server...")
    
    # Run the server
    uvicorn.run("backend.main:app", 
                host="0.0.0.0", 
                port=8000, 
                reload=True,
                reload_dirs=[str(project_root)]) 