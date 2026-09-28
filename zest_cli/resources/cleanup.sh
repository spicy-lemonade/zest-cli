#!/bin/bash
# Zest CLI Shell Cleanup Script
# This script handles cleanup when the app bundle is deleted and Python is unavailable.
# It provides a fallback for --uninstall and orphan cleanup scenarios.

set -e

# Configuration
ZEST_DIR="$HOME/.zest"
CONFIG_DIR="$HOME/Library/Application Support/Zest"
CONFIG_FILE="$CONFIG_DIR/config.json"
API_BASE="https://europe-west1-nl-cli.cloudfunctions.net"
WRAPPER_PATH="/usr/local/bin/zest"

# Model and app paths
MODEL_PATH="$ZEST_DIR/qwen3.5_9b_Q5_K_M.gguf"
APP_PATH="/Applications/Zest.app"

# Get hardware UUID for deregistration
get_hw_id() {
    ioreg -d2 -c IOPlatformExpertDevice | awk -F'"' '/IOPlatformUUID/{print $(NF-1)}'
}

# Read license data
read_license() {
    if [ -f "$CONFIG_FILE" ]; then
        grep -q '"license"' "$CONFIG_FILE" 2>/dev/null && echo "exists"
    fi
}

# Read email from license
read_license_email() {
    if [ -f "$CONFIG_FILE" ]; then
        python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('license', {}).get('email', ''))" 2>/dev/null || echo ""
    fi
}

# Read device nickname from license
read_license_nickname() {
    if [ -f "$CONFIG_FILE" ]; then
        python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('license', {}).get('device_nickname', 'this device'))" 2>/dev/null || echo "this device"
    fi
}

# Deregister device from server
deregister_device() {
    local email="$1"
    local hw_id
    hw_id=$(get_hw_id)

    if [ -n "$email" ]; then
        curl -s -X POST "$API_BASE/deregister_device" \
            -H "Content-Type: application/json" \
            -d "{\"email\": \"$email\", \"device_uuid\": \"$hw_id\"}" \
            --connect-timeout 10 >/dev/null 2>&1 || true
    fi
}

# Uninstall Zest
uninstall_zest() {
    # Deregister from server if we have license data
    local email
    local nickname
    email=$(read_license_email)
    nickname=$(read_license_nickname)

    if [ -n "$email" ]; then
        printf "\033[2K\r🌶️ Deregistering \"%s\"...\n" "$nickname"
        deregister_device "$email"
        echo "🍋 \"$nickname\" deregistered from license."
    fi

    # Delete model file
    if [ -f "$MODEL_PATH" ]; then
        rm -f "$MODEL_PATH"
        echo "🗑️  Deleted model file."

        # Create uninstall marker
        mkdir -p "$ZEST_DIR"
        touch "$ZEST_DIR/.uninstalled"

        # Remove setup marker
        rm -f "$ZEST_DIR/.setup_complete"
    fi

    # Delete app bundle if it exists
    if [ -d "$APP_PATH" ]; then
        rm -rf "$APP_PATH"
        echo "🗑️  Removed app from Applications."
    fi
}

# Remove config (simplified - just removes the whole config if the model is gone)
cleanup_config() {
    if [ ! -f "$MODEL_PATH" ]; then
        rm -f "$CONFIG_FILE"
        [ -d "$CONFIG_DIR" ] && rmdir "$CONFIG_DIR" 2>/dev/null || true

        # Clean up .zest directory if empty (except for markers)
        if [ -d "$ZEST_DIR" ]; then
            # Remove main.py fallback
            rm -f "$ZEST_DIR/main.py"
            # Check if only marker files remain
            local file_count
            file_count=$(find "$ZEST_DIR" -type f ! -name ".uninstalled" | wc -l | tr -d ' ')
            if [ "$file_count" = "0" ]; then
                rm -rf "$ZEST_DIR"
            fi
        fi
    fi
}

# Full cleanup - remove everything including this script and wrapper
full_cleanup() {
    echo "🍋 Cleanup complete."

    # Only remove wrapper if the app no longer exists
    if [ ! -d "$APP_PATH" ]; then
        # Remove wrapper (may need sudo, so try without first)
        rm -f "$WRAPPER_PATH" 2>/dev/null || sudo rm -f "$WRAPPER_PATH" 2>/dev/null || true

        # Remove this script
        rm -f "$0" 2>/dev/null || true
    fi
}

# Show status
show_status() {
    echo "🍋 Zest Status (Shell Fallback)"
    echo ""

    local model_installed="❌"
    local app_installed="❌"

    [ -f "$MODEL_PATH" ] && model_installed="✅"
    [ -d "$APP_PATH" ] && app_installed="✅"

    echo "   Model: $model_installed | App: $app_installed"
    echo ""

    if [ "$app_installed" = "❌" ]; then
        echo "   ⚠️  No app bundle found. Reinstall from DMG or run:"
        echo "      zest --uninstall"
    fi
}

# Handle orphan scenario (model exists but app deleted)
handle_orphan() {
    # Check for DMG installation markers (setup marker, main.py, or license)
    local setup_marker="$ZEST_DIR/.setup_complete"
    local main_py_marker="$ZEST_DIR/main.py"
    local has_license
    has_license=$(read_license)

    local was_dmg_install=false
    [ -f "$setup_marker" ] && was_dmg_install=true
    [ -f "$main_py_marker" ] && was_dmg_install=true
    [ -n "$has_license" ] && was_dmg_install=true

    # Check if this is an orphan situation (model exists, app deleted, was DMG install)
    if [ -f "$MODEL_PATH" ] && [ ! -d "$APP_PATH" ] && $was_dmg_install; then
        echo ""
        echo "⚠️  Zest app was removed from Applications."
        echo "   Model files still exist on this device."
        echo ""
        echo "   Options:"
        echo "   1. Clean up (remove model files and free license slot)"
        echo "   2. Keep files (reinstall from DMG to continue using Zest)"
        echo ""

        while true; do
            printf "   Enter choice [1/2]: "
            read -r choice
            case "$choice" in
                1)
                    uninstall_zest
                    cleanup_config
                    full_cleanup
                    exit 0
                    ;;
                2)
                    echo ""
                    echo "   Files kept. To reinstall:"
                    echo "   1. Download Zest.dmg"
                    echo "   2. Drag the app to Applications"
                    echo "   3. Run 'zest' from Terminal"
                    exit 0
                    ;;
                *)
                    echo "   Invalid choice. Please enter 1 or 2."
                    ;;
            esac
        done
    fi
}

# Main entry point
main() {
    local args=("$@")
    local has_uninstall=false
    local has_status=false
    local has_help=false

    # Parse arguments
    for arg in "${args[@]}"; do
        case "$arg" in
            --uninstall) has_uninstall=true ;;
            --status) has_status=true ;;
            --help|-h) has_help=true ;;
        esac
    done

    # Handle --help
    if $has_help; then
        echo "Zest CLI (Shell Fallback)"
        echo ""
        echo "This is the shell fallback for cleanup operations."
        echo "For full functionality, reinstall Zest from the DMG."
        echo ""
        echo "Available commands:"
        echo "  --uninstall              Remove all Zest files and licenses"
        echo "  --status                 Show installation status"
        exit 0
    fi

    # Handle --status
    if $has_status; then
        show_status
        exit 0
    fi

    # Handle --uninstall
    if $has_uninstall; then
        if [ ! -f "$MODEL_PATH" ] && [ ! -d "$APP_PATH" ]; then
            echo "🍋 No Zest installation found."
            exit 0
        fi

        uninstall_zest
        cleanup_config
        full_cleanup
        exit 0
    fi

    # No recognized command - check for orphan scenario
    if [ ! -f "$MODEL_PATH" ] && [ ! -d "$APP_PATH" ]; then
        echo "❌ Zest is not installed."
        echo ""
        echo "To install Zest:"
        echo "  1. Download Zest.dmg"
        echo "  2. Drag the app to Applications"
        echo "  3. Run 'zest' from Terminal"
        exit 1
    fi

    # Check for orphan situation
    handle_orphan

    # If we get here, app is deleted but user didn't choose cleanup
    # Show helpful message
    echo ""
    echo "⚠️  Zest app bundle not found."
    echo "   The model exists but the app is missing."
    echo ""
    echo "   To use Zest, either:"
    echo "   • Reinstall from the DMG"
    echo "   • Run 'zest --uninstall' to clean up"
    exit 1
}

main "$@"
