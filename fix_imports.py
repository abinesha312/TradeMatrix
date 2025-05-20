"""
Helper module to fix Python import paths
This should be imported at the top of app.py
"""
import sys
import os
from pathlib import Path

# Get the project root directory
project_root = Path(__file__).parent.absolute()

# Add project root to Python path
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    
# Also add backend directory to Python path
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
    
print(f"📂 Added these paths to Python path:")
print(f"   - {project_root}")
print(f"   - {backend_dir}") 