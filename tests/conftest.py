import os
import sys

# make the project modules importable when running "pytest" from the project directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
