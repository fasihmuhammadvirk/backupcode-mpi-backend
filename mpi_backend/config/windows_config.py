"""
Windows-specific configuration optimized for httptools protocol.
This file contains settings optimized for Windows environments.
"""

import platform

# Check if running on Windows
IS_WINDOWS = platform.system().lower() == "windows"

# Windows-specific uvicorn settings for httptools (more stable than h11)
WINDOWS_UVICORN_CONFIG = {
    "timeout_keep_alive": 60,  # Increased for httptools stability
    "timeout_graceful_shutdown": 20,  # Balanced shutdown time
    "limit_concurrency": 800,  # Higher concurrency with httptools
    "backlog": 200,  # Larger backlog for httptools
    "proxy_headers": True,  # Better proxy handling
    "forwarded_allow_ips": "*",  # Allow forwarded IPs
}

# Standard settings for non-Windows with httptools
STANDARD_UVICORN_CONFIG = {
    "timeout_keep_alive": 120,
    "timeout_graceful_shutdown": 30,
    "limit_concurrency": 1500,
    "backlog": 2048,
    "proxy_headers": True,
    "forwarded_allow_ips": "*",
}


def get_uvicorn_config():
    """Get uvicorn configuration based on platform."""
    if IS_WINDOWS:
        return WINDOWS_UVICORN_CONFIG
    return STANDARD_UVICORN_CONFIG


def is_windows():
    """Check if running on Windows."""
    return IS_WINDOWS
