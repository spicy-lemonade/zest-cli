#!/bin/bash

# Zest DMG Build Script
# Creates a distributable DMG containing the Zest CLI and model
# Usage: ./build_dmg.sh [fp16|q5]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
DIST_DIR="$PROJECT_DIR/dist"

# This version MUST match the VERSION constant in config.py
VERSION="1.0.0"
APP_NAME="Zest"
BUNDLE_ID="com.zestcli.zest"
GCS_BUCKET="nlcli-models"

# Verify version matches config.py
CONFIG_PY_VERSION=$(grep -m1 'VERSION = "' "$PROJECT_DIR/config.py" | sed 's/.*VERSION = "\([^"]*\)".*/\1/')
if [ "$VERSION" != "$CONFIG_PY_VERSION" ]; then
    echo "❌ Version mismatch!"
    echo "   build_dmg.sh: $VERSION"
    echo "   config.py: $CONFIG_PY_VERSION"
    echo "   Please update VERSION in both files to match."
    exit 1
fi

# Product configuration
PRODUCT="${1:-q5}"
case "$PRODUCT" in
    fp16|fp)
        PRODUCT="fp16"
        MODEL_NAME="qwen3_4b_fp16.gguf"
        PRODUCT_SUFFIX="-FP16"
        ;;
    q5)
        MODEL_NAME="qwen3_4b_Q5_K_M.gguf"
        PRODUCT_SUFFIX="-Q5"
        ;;
    *)
        echo "Usage: $0 [fp16|q5]"
        echo "  fp16  - Build DMG with full precision model (~8GB)"
        echo "  q5    - Build DMG with quantized model (~3GB)"
        exit 1
        ;;
esac

echo "🍋 Zest DMG Build Script v$VERSION"
echo "=================================="
echo "Building: $APP_NAME$PRODUCT_SUFFIX"
echo "Model: $MODEL_NAME"
echo ""

# Clean previous builds for this product
echo "🧹 Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR/${APP_NAME}${PRODUCT_SUFFIX}"*
mkdir -p "$BUILD_DIR" "$DIST_DIR"

# Check for required tools
echo "🔍 Checking dependencies..."
command -v python3 >/dev/null 2>&1 || { echo "❌ python3 required"; exit 1; }
command -v pip3 >/dev/null 2>&1 || { echo "❌ pip3 required"; exit 1; }

# Create virtual environment for build
echo "📦 Setting up build environment..."
python3 -m venv "$BUILD_DIR/venv"
source "$BUILD_DIR/venv/bin/activate"

# Install dependencies
pip install --upgrade pip
pip install pyinstaller
pip install -r "$PROJECT_DIR/requirements.txt"

# Download model from GCS if not present locally
MODEL_PATH="$BUILD_DIR/$MODEL_NAME"
if [ ! -f "$MODEL_PATH" ]; then
    echo "📥 Downloading model from GCS (this may take a while)..."
    if command -v gsutil >/dev/null 2>&1; then
        gsutil cp "gs://$GCS_BUCKET/$MODEL_NAME" "$MODEL_PATH"
    else
        echo "⚠️  gsutil not found. Trying public URL..."
        curl -L --progress-bar -o "$MODEL_PATH" \
            "https://storage.googleapis.com/$GCS_BUCKET/$MODEL_NAME" || {
            echo "❌ Failed to download model."
            echo "   Install gsutil: pip install gsutil"
            echo "   Or ensure the bucket is publicly accessible."
            exit 1
        }
    fi
fi

echo "✅ Model ready: $(du -h "$MODEL_PATH" | cut -f1)"

# Build executable with PyInstaller
# Using --onedir for fast startup (--onefile extracts on every launch = slow)
echo "🔨 Building executable..."
cd "$PROJECT_DIR"
pyinstaller \
    --name="zest" \
    --onedir \
    --console \
    --distpath="$BUILD_DIR/pyinstaller_dist" \
    --workpath="$BUILD_DIR/pyinstaller_work" \
    --specpath="$BUILD_DIR" \
    --hidden-import=llama_cpp \
    --hidden-import=requests \
    --hidden-import=json \
    --collect-all llama_cpp \
    main.py

# Create app bundle structure
echo "📁 Creating app bundle..."
APP_BUNDLE="$DIST_DIR/${APP_NAME}${PRODUCT_SUFFIX}.app"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# Copy executable to MacOS and dependencies to Frameworks
# PyInstaller's macOS bootloader expects Python libs at Contents/Frameworks/
cp "$BUILD_DIR/pyinstaller_dist/zest/zest" "$APP_BUNDLE/Contents/MacOS/"
chmod +x "$APP_BUNDLE/Contents/MacOS/zest"

# Move _internal contents to Frameworks (where bootloader expects them)
mkdir -p "$APP_BUNDLE/Contents/Frameworks"
cp -R "$BUILD_DIR/pyinstaller_dist/zest/_internal/"* "$APP_BUNDLE/Contents/Frameworks/"

# Copy model
echo "📦 Copying model to bundle..."
cp "$MODEL_PATH" "$APP_BUNDLE/Contents/Resources/$MODEL_NAME"

# Copy Python modules for standalone use (survives app deletion)
echo "📝 Copying standalone CLI modules..."
for pyfile in main.py config.py model.py commands.py auth.py trial.py activation.py; do
    if [ -f "$PROJECT_DIR/$pyfile" ]; then
        cp "$PROJECT_DIR/$pyfile" "$APP_BUNDLE/Contents/Resources/$pyfile"
    fi
done

# Copy cleanup.sh for shell-based cleanup (no Python required)
if [ -f "$PROJECT_DIR/resources/cleanup.sh" ]; then
    cp "$PROJECT_DIR/resources/cleanup.sh" "$APP_BUNDLE/Contents/Resources/cleanup.sh"
    chmod +x "$APP_BUNDLE/Contents/Resources/cleanup.sh"
fi

# Copy icon if exists
if [ -f "$PROJECT_DIR/resources/icon.icns" ]; then
    cp "$PROJECT_DIR/resources/icon.icns" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
fi

# Copy product-specific license
PRODUCT_UPPER=$(echo "$PRODUCT" | tr '[:lower:]' '[:upper:]')
LICENSE_FILE="$PROJECT_DIR/resources/MODEL_LICENSE_${PRODUCT_UPPER}.txt"
if [ -f "$LICENSE_FILE" ]; then
    cp "$LICENSE_FILE" "$APP_BUNDLE/Contents/Resources/MODEL_LICENSE.txt"
elif [ -f "$PROJECT_DIR/resources/MODEL_LICENSE.txt" ]; then
    cp "$PROJECT_DIR/resources/MODEL_LICENSE.txt" "$APP_BUNDLE/Contents/Resources/"
fi

# Create Info.plist
cat > "$APP_BUNDLE/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>zest-launcher</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}.${PRODUCT}</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}${PRODUCT_SUFFIX}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME} ${PRODUCT_SUFFIX}</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>ZEST</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.developer-tools</string>
    <key>ZestProduct</key>
    <string>$PRODUCT</string>
</dict>
</plist>
EOF

# Create launcher script
cat > "$APP_BUNDLE/Contents/MacOS/zest-launcher" << 'LAUNCHER'
#!/bin/bash

# Resolve symlinks to get the actual script location
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    # If SOURCE is relative, resolve it relative to the symlink's directory
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
RESOURCES_DIR="$(dirname "$SCRIPT_DIR")/Resources"

# Detect product type from app bundle name
APP_NAME="$(basename "$(dirname "$(dirname "$SCRIPT_DIR")")")"
if [[ "$APP_NAME" == *"FP16"* ]]; then
    MODEL_NAME="qwen3_4b_fp16.gguf"
    PRODUCT_NAME="FP16"
    PRODUCT_LOWER="fp16"
else
    MODEL_NAME="qwen3_4b_Q5_K_M.gguf"
    PRODUCT_NAME="Q5"
    PRODUCT_LOWER="q5"
fi

# Check if launched from Finder (will show dialog AFTER first-run setup)
LAUNCHED_FROM_FINDER=false
if [ $# -eq 0 ]; then
    PARENT_NAME="$(ps -o comm= -p $PPID 2>/dev/null)"
    if [[ "$PARENT_NAME" == *"launchd"* ]] || [[ "$PARENT_NAME" == *"Finder"* ]] || [[ "$PARENT_NAME" == *"open"* ]]; then
        LAUNCHED_FROM_FINDER=true
    fi
fi

MODEL_SRC="$RESOURCES_DIR/$MODEL_NAME"
MODEL_DEST="$HOME/.zest/$MODEL_NAME"

# First-run setup
SETUP_MARKER="$HOME/.zest/.${PRODUCT_LOWER}_setup_complete"
UNINSTALL_MARKER="$HOME/.zest/.${PRODUCT_LOWER}_uninstalled"
if [ ! -f "$SETUP_MARKER" ]; then
    mkdir -p "$HOME/.zest"

    # Remove uninstall marker if present (user is reinstalling)
    rm -f "$UNINSTALL_MARKER"

    # Copy model
    if [ ! -f "$MODEL_DEST" ] && [ -f "$MODEL_SRC" ]; then
        echo "🍋 Installing Zest $PRODUCT_NAME model (first run only)..."
        cp "$MODEL_SRC" "$MODEL_DEST"
        echo "✅ Model installed."
    fi

    # Copy standalone CLI modules for cleanup after app deletion
    for pyfile in main.py config.py model.py commands.py auth.py trial.py activation.py; do
        if [ -f "$RESOURCES_DIR/$pyfile" ]; then
            cp "$RESOURCES_DIR/$pyfile" "$HOME/.zest/$pyfile"
        fi
    done

    # Copy shell cleanup script (works without Python)
    CLEANUP_SRC="$RESOURCES_DIR/cleanup.sh"
    CLEANUP_DEST="$HOME/.zest/cleanup.sh"
    if [ -f "$CLEANUP_SRC" ]; then
        cp "$CLEANUP_SRC" "$CLEANUP_DEST"
        chmod +x "$CLEANUP_DEST"
    fi

    # Create wrapper script at /usr/local/bin/zest
    WRAPPER_PATH="/usr/local/bin/zest"
    WRAPPER_TMP="/tmp/zest_wrapper_$$"
    if [ ! -f "$WRAPPER_PATH" ]; then
        # Create temp file in /tmp (always writable)
        cat > "$WRAPPER_TMP" << 'WRAPPER_EOF'
#!/bin/bash
# Zest CLI Wrapper - Survives app deletion for cleanup

FP16_APP="/Applications/Zest-FP16.app"
Q5_APP="/Applications/Zest-Q5.app"

# Find which app to use
if [ -d "$FP16_APP" ] && [ -d "$Q5_APP" ]; then
    CONFIG_FILE="$HOME/Library/Application Support/Zest/config.json"
    if [ -f "$CONFIG_FILE" ]; then
        ACTIVE=$(grep -o '"active_product": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | cut -d'"' -f4)
        [ "$ACTIVE" = "fp16" ] && APP_PATH="$FP16_APP" || APP_PATH="$Q5_APP"
    else
        APP_PATH="$FP16_APP"
    fi
elif [ -d "$FP16_APP" ]; then
    APP_PATH="$FP16_APP"
elif [ -d "$Q5_APP" ]; then
    APP_PATH="$Q5_APP"
else
    # No apps found - use shell cleanup script (no Python required)
    SHELL_CLEANUP="$HOME/.zest/cleanup.sh"
    PYTHON_CLI="$HOME/.zest/main.py"

    if [ -f "$SHELL_CLEANUP" ]; then
        # Shell cleanup handles orphan detection, --uninstall, --status
        exec "$SHELL_CLEANUP" "$@"
    elif [ -f "$PYTHON_CLI" ] && command -v python3 >/dev/null 2>&1; then
        # Fallback to Python if available
        exec python3 "$PYTHON_CLI" "$@"
    else
        echo "❌ Zest is not installed."
        echo "   Download from https://zestcli.com"
        exit 1
    fi
fi

exec "$APP_PATH/Contents/MacOS/zest-launcher" "$@"
WRAPPER_EOF

        if [ -f "$WRAPPER_TMP" ]; then
            # Try to move without admin first
            if mv "$WRAPPER_TMP" "$WRAPPER_PATH" 2>/dev/null && chmod +x "$WRAPPER_PATH" 2>/dev/null; then
                echo "✅ Created wrapper: /usr/local/bin/zest"
            else
                # Need admin privileges - use AppleScript dialog for GUI, sudo for terminal
                if [ "$LAUNCHED_FROM_FINDER" = true ]; then
                    # Use AppleScript to get admin privileges (shows macOS auth dialog)
                    osascript -e "do shell script \"mv '$WRAPPER_TMP' '$WRAPPER_PATH' && chmod +x '$WRAPPER_PATH'\" with administrator privileges" 2>/dev/null
                else
                    # Terminal mode - use sudo
                    echo "📎 Setting up command-line access requires sudo..."
                    echo "Please enter your password to create /usr/local/bin/zest"
                    sudo mv "$WRAPPER_TMP" "$WRAPPER_PATH" && sudo chmod +x "$WRAPPER_PATH"
                    echo "✅ Created wrapper: /usr/local/bin/zest"
                    echo ""
                    echo "Add to your ~/.bashrc or ~/.zshrc (for using ? and * wildcards):"
                    echo "  alias zest='noglob /usr/local/bin/zest'"
                    echo ""
                fi
            fi
            rm -f "$WRAPPER_TMP" 2>/dev/null
        fi
    fi

    touch "$SETUP_MARKER"
fi

# If launched from Finder, show dialog and exit (after first-run setup is complete)
if [ "$LAUNCHED_FROM_FINDER" = true ]; then
    osascript -e "display dialog \"Zest CLI ($PRODUCT_NAME) installed!

Open Terminal and run a command, for example:
  zest list all files in Downloads

Add to ~/.bashrc or ~/.zshrc (for using ? and * wildcards):
  alias zest='noglob /usr/local/bin/zest'\" buttons {\"OK\"} default button \"OK\" with title \"Zest CLI\""
    exit 0
fi

# Ensure model is in place (in case it was accidentally deleted)
# Only auto-reinstall if not explicitly uninstalled by user
UNINSTALL_MARKER="$HOME/.zest/.${PRODUCT_LOWER}_uninstalled"
if [ ! -f "$MODEL_DEST" ] && [ -f "$MODEL_SRC" ] && [ ! -f "$UNINSTALL_MARKER" ]; then
    mkdir -p "$HOME/.zest"
    echo "🍋 Installing Zest $PRODUCT_NAME model..."
    cp "$MODEL_SRC" "$MODEL_DEST"
    echo "✅ Model installed."
    # Remove uninstall marker since we're reinstalling
    rm -f "$UNINSTALL_MARKER"
fi

# Run the CLI
exec "$SCRIPT_DIR/zest" "$@"
LAUNCHER
chmod +x "$APP_BUNDLE/Contents/MacOS/zest-launcher"

# Code signing (optional)
if [ -n "$APPLE_SIGNING_IDENTITY" ]; then
    echo "✍️  Signing app bundle..."
    codesign --deep --force --verify --verbose \
        --sign "$APPLE_SIGNING_IDENTITY" \
        --options runtime \
        "$APP_BUNDLE"
fi

# Create DMG staging directory
echo "📀 Creating DMG..."
DMG_STAGING="$BUILD_DIR/dmg_staging"
mkdir -p "$DMG_STAGING"

# Copy app bundle
cp -R "$APP_BUNDLE" "$DMG_STAGING/"

# Create Applications symlink
ln -s /Applications "$DMG_STAGING/Applications"

# Copy documentation (use product-specific license)
if [ -f "$LICENSE_FILE" ]; then
    cp "$LICENSE_FILE" "$DMG_STAGING/MODEL_LICENSE.txt"
else
    cp "$PROJECT_DIR/resources/MODEL_LICENSE.txt" "$DMG_STAGING/" 2>/dev/null || true
fi
cp "$PROJECT_DIR/resources/README_INSTALL.txt" "$DMG_STAGING/" 2>/dev/null || true

# Create DMG
DMG_NAME="${APP_NAME}${PRODUCT_SUFFIX}-${VERSION}.dmg"
DMG_PATH="$DIST_DIR/$DMG_NAME"

hdiutil create \
    -volname "${APP_NAME} ${PRODUCT_SUFFIX} ${VERSION}" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

# Notarization (optional)
if [ -n "$APPLE_ID" ] && [ -n "$APPLE_TEAM_ID" ]; then
    echo "📝 Notarizing DMG..."
    xcrun notarytool submit "$DMG_PATH" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "@keychain:AC_PASSWORD" \
        --wait
    xcrun stapler staple "$DMG_PATH"
fi

# Cleanup intermediate build artifacts
rm -rf "$APP_BUNDLE"
rm -rf "$DMG_STAGING"
deactivate
echo ""
echo "=============================================="
echo "✅ Build complete!"
echo "=============================================="
echo ""
echo "📦 DMG: $DMG_PATH"
echo "📏 Size: $(du -h "$DMG_PATH" | cut -f1)"
echo ""
echo "To build the other model, run:"
if [ "$PRODUCT" = "fp16" ]; then
    echo "  ./build_dmg.sh q5"
else
    echo "  ./build_dmg.sh fp16"
fi
echo ""
echo "Next steps:"
echo "1. Test the DMG by mounting and installing"
echo "2. Upload to Polar for distribution"
