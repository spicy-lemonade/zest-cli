"""
Model management: loading, updates, detection, and orphan checking for Zest CLI.
"""

import os
import sys
import subprocess
import contextlib
import multiprocessing
import time
import json
import requests

from config import (
    ZEST_DIR, MODEL_PATH, APP_PATH,
    API_BASE, VERSION, MODEL_VERSION, UPDATE_CHECK_INTERVAL, AFFIRMATIVE,
    load_config, save_config, format_connection_error
)


def is_installed() -> bool:
    """Check whether the app bundle or model file is present on this device."""
    return os.path.exists(APP_PATH) or os.path.exists(MODEL_PATH)


def check_for_orphaned_installation() -> bool:
    """
    Check if app bundle has been deleted but files remain.
    Delegates to cleanup.sh for the actual cleanup work.
    Returns True if orphaned installation was detected and user chose to clean up.
    """
    config = load_config()
    cleanup_script = os.path.join(ZEST_DIR, "cleanup.sh")

    license_data = config.get("license")

    # Check for setup marker (created during first-run DMG setup)
    setup_marker = os.path.join(ZEST_DIR, ".setup_complete")
    main_py_marker = os.path.join(ZEST_DIR, "main.py")
    was_installed_via_dmg = os.path.exists(setup_marker) or os.path.exists(main_py_marker) or license_data

    # Trigger orphan cleanup if model exists, app missing, and was installed via DMG
    if os.path.exists(MODEL_PATH) and not os.path.exists(APP_PATH) and was_installed_via_dmg:
        if os.path.exists(cleanup_script):
            try:
                result = subprocess.run([cleanup_script], check=False)
                return result.returncode == 0
            except (subprocess.SubprocessError, OSError):
                pass

        print(f"\n⚠️  Zest app was removed from Applications.")
        print("   Model files still exist on this device.")
        print("")
        print("   Run 'zest --uninstall' to clean up.")
        return True

    return False


def get_model_version() -> str:
    """Get the installed model version from config."""
    config = load_config()
    return config.get("model_version", MODEL_VERSION)


def set_model_version(version: str):
    """Save the installed model version."""
    config = load_config()
    config["model_version"] = version
    save_config(config)


def request_model_download_url() -> dict | None:
    """Request a signed download URL from the backend. Returns {"download_url": ..., "model_size_bytes": ...} or None."""
    config = load_config()
    license_data = config.get("license", {})
    trial_data = config.get("trial", {})
    email = license_data.get("email") or trial_data.get("email")

    if not email:
        return None

    from trial import get_hw_id
    hw_id = get_hw_id()

    try:
        res = requests.post(
            f"{API_BASE}/get_model_download_url",
            json={"email": email, "device_id": hw_id},
            timeout=15
        )
        if res.status_code == 200:
            return res.json()
        else:
            print(f"\n❌ Could not get download URL: {res.text}")
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Connection error: {format_connection_error(e)}")

    return None


def ensure_model_downloaded():
    """Check if model file exists; if not, download it via signed URL."""
    if os.path.exists(MODEL_PATH):
        return

    print(f"\n📥 Model not found. Downloading...")

    data = request_model_download_url()
    if not data or not data.get("download_url"):
        print("❌ Could not get model download URL. Please try again later.")
        sys.exit(1)

    os.makedirs(ZEST_DIR, exist_ok=True)
    model_size = data.get("model_size_bytes", 0)

    if download_model_with_progress(data["download_url"], MODEL_PATH, model_size):
        print(f"✅ Model installed.")
    else:
        print("❌ Model download failed. Please try again.")
        sys.exit(1)


def download_model_with_progress(url: str, dest_path: str, total_size: int = 0) -> bool:
    """Download a model file with progress bar. Returns True if successful."""
    temp_path = dest_path + ".download"

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        if total_size == 0:
            total_size = int(response.headers.get("content-length", 0))

        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB chunks

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    _print_download_progress(downloaded, total_size)

        print()  # New line after progress bar

        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(temp_path, dest_path)

        return True

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Download failed: {format_connection_error(e)}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False
    except KeyboardInterrupt:
        print("\n❌ Download cancelled.")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


def _print_download_progress(downloaded: int, total_size: int):
    """Print download progress bar."""
    if total_size > 0:
        percent = (downloaded / total_size) * 100
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        bar_width = 30
        filled = int(bar_width * downloaded / total_size)
        bar = "█" * filled + "░" * (bar_width - filled)
        print(f"\r   [{bar}] {percent:.1f}% ({downloaded_mb:.0f}/{total_mb:.0f} MB)", end="", flush=True)
    else:
        downloaded_mb = downloaded / (1024 * 1024)
        print(f"\r   Downloaded: {downloaded_mb:.0f} MB", end="", flush=True)


def check_for_updates() -> None:
    """Check for available updates. Only checks once per UPDATE_CHECK_INTERVAL."""
    config = load_config()
    last_check = config.get("last_update_check", 0)
    current_time = time.time()

    if (current_time - last_check) < UPDATE_CHECK_INTERVAL:
        return

    current_model_version = get_model_version()

    try:
        res = requests.post(
            f"{API_BASE}/check_version",
            json={
                "current_version": VERSION,
                "current_model_version": current_model_version
            },
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            config["last_update_check"] = current_time
            save_config(config)

            _handle_cli_update(data)
            _handle_model_update(data)

    except (requests.exceptions.RequestException, json.JSONDecodeError):
        pass  # Silently fail


def _handle_cli_update(data: dict):
    """Display CLI update notification if available."""
    if not data.get("cli_update_available"):
        return

    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  🍋 CLI Update available: v{data.get('latest_cli_version', 'new')}")
    if data.get("update_message"):
        msg = data.get("update_message")
        print(f"│  {msg[:45]}")
    print(f"│  Download: {data.get('update_url', 'https://zestcli.com')}")
    print("└─────────────────────────────────────────────────┘")
    print("")


def _handle_model_update(data: dict):
    """Display model update notification and offer download if available."""
    if not data.get("model_update_available"):
        return

    latest_model_version = data.get("latest_model_version", "new")
    model_size = data.get("model_size_bytes", 0)
    size_gb = model_size / (1024 * 1024 * 1024) if model_size else 0

    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  🍋 Model Update available: v{latest_model_version}")
    if size_gb > 0:
        print(f"│  Size: {size_gb:.1f} GB")
    print("└─────────────────────────────────────────────────┘")
    print("")

    choice = input("🍋 Download new model now? [y/n]: ").strip().lower()
    if choice not in AFFIRMATIVE:
        print("   Skipping model update. Run 'zest --update' later to update.")
        return

    print("")
    print(f"📥 Downloading model...")

    url_data = request_model_download_url()
    if not url_data or not url_data.get("download_url"):
        print("❌ Could not get model download URL. Please try again later.")
        return

    backup_path = MODEL_PATH + ".backup"
    if os.path.exists(MODEL_PATH):
        os.rename(MODEL_PATH, backup_path)

    success = download_model_with_progress(url_data["download_url"], MODEL_PATH, model_size)

    if success:
        set_model_version(latest_model_version)
        print(f"✅ Model updated to v{latest_model_version}")
        if os.path.exists(backup_path):
            os.remove(backup_path)
    else:
        if os.path.exists(backup_path):
            os.rename(backup_path, MODEL_PATH)
            print("   Restored previous model.")


@contextlib.contextmanager
def suppress_c_logs():
    """Context manager to suppress C library stderr output."""
    stderr_fd = sys.stderr.fileno()
    saved_stderr_fd = os.dup(stderr_fd)
    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), stderr_fd)
        yield
    finally:
        os.dup2(saved_stderr_fd, stderr_fd)
        os.close(saved_stderr_fd)


def load_model():
    """Load the LLM model with GPU acceleration fallback to CPU."""
    from llama_cpp import Llama

    if not os.path.exists(MODEL_PATH):
        sys.stderr.write(f"❌ Error: Model not found at {MODEL_PATH}\n")
        sys.stderr.write("   Please ensure Zest is properly installed.\n")
        sys.exit(1)

    recommended_threads = max(1, multiprocessing.cpu_count() // 2)
    params = {
        "model_path": MODEL_PATH,
        "n_ctx": 1024,
        "n_batch": 512,
        "n_threads": recommended_threads,
        "verbose": False
    }

    with suppress_c_logs():
        try:
            return Llama(**params, n_gpu_layers=-1)
        except Exception:
            sys.stderr.write("⚠️ GPU acceleration failed, falling back to CPU...\n")
            return Llama(**params, n_gpu_layers=0)
