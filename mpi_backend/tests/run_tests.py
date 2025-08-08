#!/usr/bin/env python3
"""
Simple script to run tests with proper Python path setup.
"""

import os
import sys
import subprocess


def main():
    # Add the current directory to Python path
    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_root)
    
    # Set environment variable for pytest
    os.environ['PYTHONPATH'] = project_root
    
    # Run pytest with the same arguments passed to this script
    cmd = ['pytest'] + sys.argv[1:]
    
    print(f"Running: {' '.join(cmd)}")
    print(f"Python path: {project_root}")
    
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    exit(main()) 