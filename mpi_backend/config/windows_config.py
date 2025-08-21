"""
Windows-specific configuration to prevent h11 protocol errors.
This file contains settings optimized for Windows environments.
"""

import platform

# Check if running on Windows
IS_WINDOWS = platform.system().lower() == "windows"

# Windows-specific uvicorn settings
WINDOWS_UVICORN_CONFIG = {
    "timeout_keep_alive": 30,  # Reduced keep-alive timeout
    "timeout_graceful_shutdown": 15,  # Faster shutdown
    "limit_concurrency": 500,  # Lower concurrency limit
    "backlog": 100,  # Smaller connection backlog
    "proxy_headers": True,  # Better proxy handling
    "forwarded_allow_ips": "*",  # Allow forwarded IPs
}

# Standard settings for non-Windows
STANDARD_UVICORN_CONFIG = {
    "timeout_keep_alive": 65,
    "timeout_graceful_shutdown": 30,
    "limit_concurrency": 1000,
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
