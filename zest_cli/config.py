"""
Configuration constants and config file management for Zest CLI.
"""

import os
import json

# --- Version ---
VERSION = "1.0.0"
MODEL_VERSION = "1.0.0"

# --- Product ---
PRODUCT_NAME = "Zest CLI"

# --- Paths ---
ZEST_DIR = os.path.expanduser("~/.zest")
MODEL_PATH = os.path.join(ZEST_DIR, "qwen3.5_9b_Q5_K_M.gguf")
APP_PATH = "/Applications/Zest.app"
CONFIG_DIR = os.path.expanduser("~/Library/Application Support/Zest")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# --- API ---
API_BASE = "https://europe-west1-nl-cli.cloudfunctions.net"

# --- Timing ---
LEASE_DURATION = 1209600  # 14 days in seconds
UPDATE_CHECK_INTERVAL = 1209600  # Check for updates every 2 weeks
TRIAL_CHECK_INTERVAL = 86400  # 24 hours

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


def format_connection_error(e: Exception) -> str:
    """Format a connection error for user display without revealing internal URLs."""
    error_str = str(e).lower()
    if "timed out" in error_str or "timeout" in error_str:
        return "Connection timed out"
    if "connection refused" in error_str:
        return "Connection refused"
    if "name or service not known" in error_str or "getaddrinfo" in error_str:
        return "Could not resolve server"
    if "connection" in error_str:
        return "Could not connect to server"
    return "Network error"
