"""
Configuration constants and config file management for Zest CLI.
"""

import os
import json

# --- Version ---
VERSION = "1.0.0"
MODEL_VERSION = "1.0.0"

# --- Paths ---
ZEST_DIR = os.path.expanduser("~/.zest")
MODEL_PATH_FP16 = os.path.join(ZEST_DIR, "qwen3_4b_fp16.gguf")
MODEL_PATH_Q5 = os.path.join(ZEST_DIR, "qwen3_4b_Q5_K_M.gguf")
CONFIG_DIR = os.path.expanduser("~/Library/Application Support/Zest")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# --- API ---
API_BASE = "https://europe-west1-nl-cli-dev.cloudfunctions.net"  # TODO: Change to nl-cli for production

# --- Timing ---
LEASE_DURATION = 1209600  # 14 days in seconds
UPDATE_CHECK_INTERVAL = 1209600  # Check for updates every 2 weeks
TRIAL_CHECK_INTERVAL = 30  # TODO: Change to 86400 (24 hours) for production

# --- App Bundles ---
APP_PATHS = {
    "fp16": "/Applications/Zest-FP16.app",
    "q5": "/Applications/Zest-Q5.app"
}

# --- Products ---
PRODUCTS = {
    "fp16": {"path": MODEL_PATH_FP16, "name": "FP16 (Full Precision)"},
    "q5": {"path": MODEL_PATH_Q5, "name": "Q5 (Quantized)"}
}

# --- Response Constants ---
AFFIRMATIVE = ("y", "yes", "yeah", "yep", "sure", "ok", "okay")
NEGATIVE = ("n", "no", "nah", "nope")


def load_config() -> dict:
    """Load configuration from disk."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_config(config: dict):
    """Save configuration to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)
