#!/bin/bash

# Zest DMG Build Script
# Creates a distributable DMG containing the Zest CLI and model
# Usage: ./build_dmg.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
DIST_DIR="$PROJECT_DIR/dist"

# This version must match the VERSION constant in config.py
VERSION="1.0.0"
APP_NAME="Zest"
BUNDLE_ID="com.zestcli.zest"
MODEL_NAME="qwen3.5_9b_Q5_K_M.gguf"

# Verify version matches config.py
CONFIG_PY_VERSION=$(grep -m1 'VERSION = "' "$PROJECT_DIR/config.py" | sed 's/.*VERSION = "\([^"]*\)".*/\1/')
if [ "$VERSION" != "$CONFIG_PY_VERSION" ]; then
    echo "❌ Version mismatch!"
    echo "   build_dmg.sh: $VERSION"
    echo "   config.py: $CONFIG_PY_VERSION"
    echo "   Please update VERSION in both files to match."
    exit 1
fi

echo "🍋 Zest DMG Build Script v$VERSION"
echo "=================================="
echo "Building: $APP_NAME"
echo "Model: $MODEL_NAME"
echo ""

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR/${APP_NAME}"*
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
    --hidden-import=charset_normalizer \
    --hidden-import=json \
    --collect-all llama_cpp \
    --collect-all charset_normalizer \
    --copy-metadata charset-normalizer \
    --copy-metadata requests \
    main.py

# Create app bundle structure
echo "📁 Creating app bundle..."
APP_BUNDLE="$DIST_DIR/${APP_NAME}.app"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# Copy executable to MacOS and dependencies to Frameworks
# PyInstaller's macOS bootloader expects Python libs at Contents/Frameworks/
cp "$BUILD_DIR/pyinstaller_dist/zest/zest" "$APP_BUNDLE/Contents/MacOS/"
chmod +x "$APP_BUNDLE/Contents/MacOS/zest"

# Move _internal contents to Frameworks (where bootloader expects them)
mkdir -p "$APP_BUNDLE/Contents/Frameworks"
cp -R "$BUILD_DIR/pyinstaller_dist/zest/_internal/"* "$APP_BUNDLE/Contents/Frameworks/"

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

# Copy model license
if [ -f "$PROJECT_DIR/resources/MODEL_LICENSE.txt" ]; then
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
    <string>${BUNDLE_ID}</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME} CLI</string>
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

# Check if launched from Finder (will show dialog AFTER first-run setup)
LAUNCHED_FROM_FINDER=false
if [ $# -eq 0 ]; then
    PARENT_NAME="$(ps -o comm= -p $PPID 2>/dev/null)"
    if [[ "$PARENT_NAME" == *"launchd"* ]] || [[ "$PARENT_NAME" == *"Finder"* ]] || [[ "$PARENT_NAME" == *"open"* ]]; then
        LAUNCHED_FROM_FINDER=true
    fi
fi

# First-run setup
SETUP_MARKER="$HOME/.zest/.setup_complete"
UNINSTALL_MARKER="$HOME/.zest/.uninstalled"
if [ ! -f "$SETUP_MARKER" ]; then
    mkdir -p "$HOME/.zest"

    # Remove uninstall marker if present (user is reinstalling)
    rm -f "$UNINSTALL_MARKER"

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

    touch "$SETUP_MARKER"
fi

# Ensure the CLI wrapper points at this app. Checked on every launch, not
# just first-run: dragging the app to the Trash (instead of running
# `zest --uninstall`) leaves .setup_complete in ~/.zest in place, so
# first-run setup alone would never repair a wrapper left over from an
# older install (e.g. one still pointing at Zest-Lite.app/Zest-Hot.app).
WRAPPER_PATH="/usr/local/bin/zest"
if [ ! -f "$WRAPPER_PATH" ] || ! grep -q '/Applications/Zest.app' "$WRAPPER_PATH" 2>/dev/null; then
    WRAPPER_TMP="/tmp/zest_wrapper_$$"
    cat > "$WRAPPER_TMP" << 'WRAPPER_EOF'
#!/bin/bash
# Zest CLI Wrapper - Survives app deletion for cleanup

APP_PATH="/Applications/Zest.app"

if [ ! -d "$APP_PATH" ]; then
    # App not found - use shell cleanup script (no Python required)
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

# If launched from Finder, show dialog and exit (after first-run setup is complete)
if [ "$LAUNCHED_FROM_FINDER" = true ]; then
    osascript -e "display dialog \"Zest CLI installed!

Open Terminal and run a command, for example:
  zest list all files in Downloads

Add to ~/.bashrc or ~/.zshrc (for using ? and * wildcards):
  alias zest='noglob /usr/local/bin/zest'\" buttons {\"OK\"} default button \"OK\" with title \"Zest CLI\""
    exit 0
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

# Copy documentation
cp "$PROJECT_DIR/resources/MODEL_LICENSE.txt" "$DMG_STAGING/" 2>/dev/null || true
cp "$PROJECT_DIR/resources/README_INSTALL.txt" "$DMG_STAGING/" 2>/dev/null || true

# Create DMG
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
DMG_PATH="$DIST_DIR/$DMG_NAME"

hdiutil create \
    -volname "${APP_NAME} ${VERSION}" \
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
echo "Next steps:"
echo "1. Test the DMG by mounting and installing"
echo "2. Upload to Polar for distribution"
