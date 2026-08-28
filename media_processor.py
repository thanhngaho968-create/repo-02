#!/usr/bin/env python3
import os
import sys

# Ensure current working directory is on pythonpath
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from runners.media_processor import main

if __name__ == "__main__":
    main()
