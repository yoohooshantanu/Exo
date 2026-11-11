"""
modules/config.py
Shared configuration and version constants for the Exo platform.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Bump to 5.0.0 for XUV escape physics replacement
HABITABILITY_MODEL_VERSION = "5.0.0"
ORBITAL_MODEL_VERSION = "3.1.0"
BIOSIG_MODEL_VERSION = "3.0.0"
ANOMALY_MODEL_VERSION = "1.0.0"
TAXONOMY_MODEL_VERSION = "1.0.0"
SYNTHESIS_MODEL_VERSION = "2.0.0"

RETRIEVAL_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "retrievals"
DEFAULT_ORBITAL_SEED = 42
