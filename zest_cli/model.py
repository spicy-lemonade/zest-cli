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
    ZEST_DIR, MODEL_PATH_FP16, MODEL_PATH_Q5, PRODUCTS, APP_PATHS,
    API_BASE, VERSION, MODEL_VERSION, UPDATE_CHECK_INTERVAL, AFFIRMATIVE,
    load_config, save_config
)


def get_active_product() -> str | None:
    """
    Determine which product to use.
    Priority: 1) User preference, 2) fp16 if available, 3) q5 if available
    Only considers products where the app bundle is installed (DMG mode).
    Returns None if no models are installed.
    """
    config = load_config()
    preferred = config.get("active_product")

    # If user has a preference and both model and app exist, use it
    if preferred:
        app_exists = os.path.exists(APP_PATHS.get(preferred, ""))
        model_exists = os.path.exists(PRODUCTS[preferred]["path"])
        if app_exists and model_exists:
            return preferred

    # Otherwise, prefer fp16 over q5 if available AND app is installed
    for product in ["fp16", "q5"]:
        app_exists = os.path.exists(APP_PATHS[product])
        model_exists = os.path.exists(PRODUCTS[product]["path"])
        if app_exists and model_exists:
            return product

    # Fallback: if no app bundle but model exists, still allow (dev/manual mode)
    if os.path.exists(MODEL_PATH_FP16):
        return "fp16"
    if os.path.exists(MODEL_PATH_Q5):
        return "q5"

    return None


def check_for_orphaned_installation(active_product: str) -> bool:
    """
    Check if app bundle has been deleted but files remain for the ACTIVE product only.
    Delegates to cleanup.sh for the actual cleanup work.
    Returns True if orphaned installation was detected and user chose to clean up.
    """
    config = load_config()
    cleanup_script = os.path.join(ZEST_DIR, "cleanup.sh")

    product = active_product
    app_path = APP_PATHS[product]
    model_path = PRODUCTS[product]["path"]
    product_key = f"{product}_license"
    license_data = config.get(product_key)

    # Check for setup marker (created during first-run DMG setup)
    setup_marker = os.path.join(ZEST_DIR, f".{product}_setup_complete")
    main_py_marker = os.path.join(ZEST_DIR, "main.py")
    was_installed_via_dmg = os.path.exists(setup_marker) or os.path.exists(main_py_marker) or license_data

    # Trigger orphan cleanup if model exists, app missing, and was installed via DMG
    if os.path.exists(model_path) and not os.path.exists(app_path) and was_installed_via_dmg:
        if os.path.exists(cleanup_script):
            try:
                result = subprocess.run([cleanup_script], check=False)
                return result.returncode == 0
            except (subprocess.SubprocessError, OSError):
                pass

        print(f"\n⚠️  Zest {PRODUCTS[product]['name']} app was removed from Applications.")
        print("   Model files still exist on this device.")
        print("")
        print("   Run 'zest --uninstall' to clean up.")
        return True

    return False


def get_model_version(product: str) -> str:
    """Get the installed model version for a product from config."""
    config = load_config()
    return config.get(f"{product}_model_version", MODEL_VERSION)


def set_model_version(product: str, version: str):
    """Save the installed model version for a product."""
    config = load_config()
    config[f"{product}_model_version"] = version
    save_config(config)


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
        print(f"\n❌ Download failed: {e}")
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


def check_for_updates(product: str) -> None:
    """Check for available updates. Only checks once per UPDATE_CHECK_INTERVAL."""
    config = load_config()
    last_check = config.get("last_update_check", 0)
    current_time = time.time()

    if (current_time - last_check) < UPDATE_CHECK_INTERVAL:
        return

    current_model_version = get_model_version(product)

    try:
        res = requests.post(
            f"{API_BASE}/check_version",
            json={
                "current_version": VERSION,
                "current_model_version": current_model_version,
                "product": product
            },
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            config["last_update_check"] = current_time
            save_config(config)

            _handle_cli_update(data)
            _handle_model_update(data, product)

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


def _handle_model_update(data: dict, product: str):
    """Display model update notification and offer download if available."""
    if not data.get("model_update_available"):
        return

    latest_model_version = data.get("latest_model_version", "new")
    model_size = data.get("model_size_bytes", 0)
    size_gb = model_size / (1024 * 1024 * 1024) if model_size else 0

    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  🍋 Model Update available: v{latest_model_version}")
    print(f"│  Product: {PRODUCTS[product]['name']}")
    if size_gb > 0:
        print(f"│  Size: {size_gb:.1f} GB")
    print("└─────────────────────────────────────────────────┘")
    print("")

    choice = input("🍋 Download new model now? [y/n]: ").strip().lower()
    if choice not in AFFIRMATIVE:
        print("   Skipping model update. Run 'zest --update' later to update.")
        return

    print("")
    print(f"📥 Downloading {PRODUCTS[product]['name']} model...")
    model_path = PRODUCTS[product]["path"]
    download_url = data.get("model_download_url")

    if not download_url:
        print("❌ No download URL available.")
        return

    backup_path = model_path + ".backup"
    if os.path.exists(model_path):
        os.rename(model_path, backup_path)

    success = download_model_with_progress(download_url, model_path, model_size)

    if success:
        set_model_version(product, latest_model_version)
        print(f"✅ Model updated to v{latest_model_version}")
        if os.path.exists(backup_path):
            os.remove(backup_path)
    else:
        if os.path.exists(backup_path):
            os.rename(backup_path, model_path)
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


def load_model(product: str):
    """Load the LLM model with GPU acceleration fallback to CPU."""
    from llama_cpp import Llama

    model_path = PRODUCTS[product]["path"]
    if not os.path.exists(model_path):
        sys.stderr.write(f"❌ Error: Model not found at {model_path}\n")
        sys.stderr.write("   Please ensure Zest is properly installed.\n")
        sys.exit(1)

    recommended_threads = max(1, multiprocessing.cpu_count() // 2)
    params = {
        "model_path": model_path,
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
