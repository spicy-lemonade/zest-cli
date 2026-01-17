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

# Model paths
MODEL_PATH_FP16="$ZEST_DIR/qwen3_4b_fp16.gguf"
MODEL_PATH_Q5="$ZEST_DIR/qwen3_4b_Q5_K_M.gguf"

# App bundle paths
FP16_APP="/Applications/Zest-FP16.app"
Q5_APP="/Applications/Zest-Q5.app"

# Get hardware UUID for deregistration
get_hw_id() {
    ioreg -d2 -c IOPlatformExpertDevice | awk -F'"' '/IOPlatformUUID/{print $(NF-1)}'
}

# Read a value from config.json
read_config() {
    local key="$1"
    if [ -f "$CONFIG_FILE" ]; then
        grep -o "\"$key\": *\"[^\"]*\"" "$CONFIG_FILE" 2>/dev/null | cut -d'"' -f4
    fi
}

# Read license data for a product
read_license() {
    local product="$1"
    local key="${product}_license"
    if [ -f "$CONFIG_FILE" ]; then
        # Check if the license key exists in config
        grep -q "\"$key\"" "$CONFIG_FILE" 2>/dev/null && echo "exists"
    fi
}

# Read email from license
read_license_email() {
    local product="$1"
    if [ -f "$CONFIG_FILE" ]; then
        # Extract email from nested license object - simplified extraction
        python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('${product}_license', {}).get('email', ''))" 2>/dev/null || echo ""
    fi
}

# Read device nickname from license
read_license_nickname() {
    local product="$1"
    if [ -f "$CONFIG_FILE" ]; then
        python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('${product}_license', {}).get('device_nickname', 'this device'))" 2>/dev/null || echo "this device"
    fi
}

# Deregister device from server
deregister_device() {
    local email="$1"
    local product="$2"
    local hw_id
    hw_id=$(get_hw_id)

    if [ -n "$email" ]; then
        curl -s -X POST "$API_BASE/deregister_device" \
            -H "Content-Type: application/json" \
            -d "{\"email\": \"$email\", \"device_uuid\": \"$hw_id\", \"product\": \"$product\"}" \
            --connect-timeout 10 >/dev/null 2>&1 || true
    fi
}

# Uninstall a specific product
uninstall_product() {
    local product="$1"
    local model_path
    local app_path
    local product_name

    if [ "$product" = "fp16" ]; then
        model_path="$MODEL_PATH_FP16"
        app_path="$FP16_APP"
        product_name="FP16 (Full Precision)"
    else
        model_path="$MODEL_PATH_Q5"
        app_path="$Q5_APP"
        product_name="Q5 (Quantized)"
    fi

    # Deregister from server if we have license data
    local email
    local nickname
    email=$(read_license_email "$product")
    nickname=$(read_license_nickname "$product")

    if [ -n "$email" ]; then
        printf "\\033[K"
        echo "🌶\033[0m  Deregistering \"$nickname\" from $product_name..."
        deregister_device "$email" "$product"
        echo "🍋 \"$nickname\" deregistered from $product_name license."
    fi

    # Delete model file
    if [ -f "$model_path" ]; then
        rm -f "$model_path"
        echo "🗑️  Deleted $product_name model file."

        # Create uninstall marker
        mkdir -p "$ZEST_DIR"
        touch "$ZEST_DIR/.${product}_uninstalled"

        # Remove setup marker
        rm -f "$ZEST_DIR/.${product}_setup_complete"
    fi

    # Delete app bundle if it exists
    if [ -d "$app_path" ]; then
        rm -rf "$app_path"
        echo "🗑️  Removed $product_name app from Applications."
    fi
}

# Remove config entry for a product (simplified - just removes the whole config if both gone)
cleanup_config() {
    # Check if any licenses remain
    local fp16_model_exists=false
    local q5_model_exists=false

    [ -f "$MODEL_PATH_FP16" ] && fp16_model_exists=true
    [ -f "$MODEL_PATH_Q5" ] && q5_model_exists=true

    # If no models left, clean up everything
    if ! $fp16_model_exists && ! $q5_model_exists; then
        rm -f "$CONFIG_FILE"
        [ -d "$CONFIG_DIR" ] && rmdir "$CONFIG_DIR" 2>/dev/null || true

        # Clean up .zest directory if empty (except for markers)
        if [ -d "$ZEST_DIR" ]; then
            # Remove main.py fallback
            rm -f "$ZEST_DIR/main.py"
            # Check if only marker files remain
            local file_count
            file_count=$(find "$ZEST_DIR" -type f ! -name ".*_uninstalled" | wc -l | tr -d ' ')
            if [ "$file_count" = "0" ]; then
                rm -rf "$ZEST_DIR"
            fi
        fi
    fi
}

# Full cleanup - remove everything including this script and wrapper
full_cleanup() {
    echo "🍋 Cleanup complete."

    # Check if we should remove the wrapper
    local fp16_exists=false
    local q5_exists=false
    [ -d "$FP16_APP" ] && fp16_exists=true
    [ -d "$Q5_APP" ] && q5_exists=true

    # Only remove wrapper if no apps remain
    if ! $fp16_exists && ! $q5_exists; then
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

    local fp16_installed="❌"
    local q5_installed="❌"
    local fp16_app="❌"
    local q5_app="❌"

    [ -f "$MODEL_PATH_FP16" ] && fp16_installed="✅"
    [ -f "$MODEL_PATH_Q5" ] && q5_installed="✅"
    [ -d "$FP16_APP" ] && fp16_app="✅"
    [ -d "$Q5_APP" ] && q5_app="✅"

    echo "   FP16 (Full Precision):"
    echo "      Model: $fp16_installed | App: $fp16_app"
    echo "   Q5 (Quantized):"
    echo "      Model: $q5_installed | App: $q5_app"
    echo ""

    if [ "$fp16_app" = "❌" ] && [ "$q5_app" = "❌" ]; then
        echo "   ⚠️  No app bundles found. Reinstall from DMG or run:"
        echo "      zest --uninstall"
    fi
}

# Handle orphan scenario (model exists but app deleted)
handle_orphan() {
    local product="$1"
    local model_path
    local app_path
    local product_name

    if [ "$product" = "fp16" ]; then
        model_path="$MODEL_PATH_FP16"
        app_path="$FP16_APP"
        product_name="FP16 (Full Precision)"
    else
        model_path="$MODEL_PATH_Q5"
        app_path="$Q5_APP"
        product_name="Q5 (Quantized)"
    fi

    # Check for DMG installation markers (setup marker, main.py, or license)
    local setup_marker="$ZEST_DIR/.${product}_setup_complete"
    local main_py_marker="$ZEST_DIR/main.py"
    local has_license
    has_license=$(read_license "$product")

    local was_dmg_install=false
    [ -f "$setup_marker" ] && was_dmg_install=true
    [ -f "$main_py_marker" ] && was_dmg_install=true
    [ -n "$has_license" ] && was_dmg_install=true

    # Check if this is an orphan situation (model exists, app deleted, was DMG install)
    if [ -f "$model_path" ] && [ ! -d "$app_path" ] && $was_dmg_install; then
        echo ""
        echo "⚠️  Zest $product_name app was removed from Applications."
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
                    uninstall_product "$product"
                    cleanup_config
                    full_cleanup
                    exit 0
                    ;;
                2)
                    echo ""
                    echo "   Files kept. To reinstall:"
                    echo "   1. Download Zest-${product_name%% *}.dmg"
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

# Determine active product
get_active_product() {
    # Check config for preference
    local preferred
    preferred=$(read_config "active_product")

    if [ -n "$preferred" ]; then
        local model_path
        [ "$preferred" = "fp16" ] && model_path="$MODEL_PATH_FP16" || model_path="$MODEL_PATH_Q5"
        [ -f "$model_path" ] && echo "$preferred" && return
    fi

    # Fallback: prefer fp16 over q5
    [ -f "$MODEL_PATH_FP16" ] && echo "fp16" && return
    [ -f "$MODEL_PATH_Q5" ] && echo "q5" && return

    echo ""
}

# Main entry point
main() {
    local args=("$@")
    local has_uninstall=false
    local has_status=false
    local has_help=false
    local product=""

    # Parse arguments
    for arg in "${args[@]}"; do
        case "$arg" in
            --uninstall) has_uninstall=true ;;
            --status) has_status=true ;;
            --help|-h) has_help=true ;;
            --fp|--fp16) product="fp16" ;;
            --q5) product="q5" ;;
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
        echo "  --uninstall        Remove all Zest files and licenses"
        echo "  --uninstall --fp   Remove FP16 only"
        echo "  --uninstall --q5   Remove Q5 only"
        echo "  --status           Show installation status"
        exit 0
    fi

    # Handle --status
    if $has_status; then
        show_status
        exit 0
    fi

    # Handle --uninstall
    if $has_uninstall; then
        if [ -n "$product" ]; then
            # Uninstall specific product
            uninstall_product "$product"
        else
            # Determine what to uninstall
            local fp16_exists=false
            local q5_exists=false
            [ -f "$MODEL_PATH_FP16" ] && fp16_exists=true
            [ -f "$MODEL_PATH_Q5" ] && q5_exists=true

            if ! $fp16_exists && ! $q5_exists; then
                echo "🍋 No Zest models are installed."
                exit 0
            fi

            if $fp16_exists && $q5_exists; then
                echo "🍋 Both models are installed:"
                echo "   1. FP16 (Full Precision)"
                echo "   2. Q5 (Quantized)"
                echo "   3. Both"
                echo ""
                while true; do
                    printf "Which would you like to uninstall? [1/2/3]: "
                    read -r choice
                    case "$choice" in
                        1) uninstall_product "fp16"; break ;;
                        2) uninstall_product "q5"; break ;;
                        3) uninstall_product "fp16"; uninstall_product "q5"; break ;;
                        *) echo "❌ Invalid choice. Please enter 1, 2, or 3." ;;
                    esac
                done
            elif $fp16_exists; then
                uninstall_product "fp16"
            else
                uninstall_product "q5"
            fi
        fi

        cleanup_config
        full_cleanup
        exit 0
    fi

    # No recognized command - check for orphan scenario
    local active_product
    active_product=$(get_active_product)

    if [ -z "$active_product" ]; then
        echo "❌ No Zest models are installed."
        echo ""
        echo "To install Zest:"
        echo "  1. Download Zest-FP16.dmg or Zest-Q5.dmg"
        echo "  2. Drag the app to Applications"
        echo "  3. Run 'zest' from Terminal"
        exit 1
    fi

    # Check for orphan situation
    handle_orphan "$active_product"

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
