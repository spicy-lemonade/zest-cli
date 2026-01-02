#!/bin/bash

# Zest CLI Post-Install Script
# Run this after dragging Zest-FP16.app or Zest-Q5.app to Applications

set -e

echo "🍋 Zest CLI Installer"
echo "====================="
echo ""

FP16_APP="/Applications/Zest-FP16.app"
Q5_APP="/Applications/Zest-Q5.app"
ZEST_DIR="$HOME/.zest"

# Detect which app(s) are installed
FP16_INSTALLED=false
Q5_INSTALLED=false

if [ -d "$FP16_APP" ]; then
    FP16_INSTALLED=true
    echo "✅ Found: Zest-FP16.app"
fi

if [ -d "$Q5_APP" ]; then
    Q5_INSTALLED=true
    echo "✅ Found: Zest-Q5.app"
fi

if ! $FP16_INSTALLED && ! $Q5_INSTALLED; then
    echo "❌ No Zest apps found in /Applications"
    echo "   Please drag Zest-FP16.app or Zest-Q5.app to Applications first."
    exit 1
fi

echo ""

# Create ~/.zest directory
echo "📁 Creating Zest directory..."
mkdir -p "$ZEST_DIR"

# Copy models to ~/.zest if not already there
if $FP16_INSTALLED; then
    MODEL_NAME="qwen3_4b_fp16.gguf"
    MODEL_SRC="$FP16_APP/Contents/Resources/$MODEL_NAME"
    MODEL_DEST="$ZEST_DIR/$MODEL_NAME"
    if [ ! -f "$MODEL_DEST" ] && [ -f "$MODEL_SRC" ]; then
        echo "📦 Copying FP16 model (this may take a moment)..."
        cp "$MODEL_SRC" "$MODEL_DEST"
        echo "✅ FP16 model installed"
    fi
fi

if $Q5_INSTALLED; then
    MODEL_NAME="qwen3_4b_Q5_K_M.gguf"
    MODEL_SRC="$Q5_APP/Contents/Resources/$MODEL_NAME"
    MODEL_DEST="$ZEST_DIR/$MODEL_NAME"
    if [ ! -f "$MODEL_DEST" ] && [ -f "$MODEL_SRC" ]; then
        echo "📦 Copying Q5 model (this may take a moment)..."
        cp "$MODEL_SRC" "$MODEL_DEST"
        echo "✅ Q5 model installed"
    fi
fi

# Copy Python CLI to ~/.zest for standalone use (survives app deletion)
echo "📝 Installing standalone CLI..."
MAIN_PY_FOUND=false

if $FP16_INSTALLED && [ -f "$FP16_APP/Contents/Resources/main.py" ]; then
    cp "$FP16_APP/Contents/Resources/main.py" "$ZEST_DIR/"
    MAIN_PY_FOUND=true
fi

if $Q5_INSTALLED && [ -f "$Q5_APP/Contents/Resources/main.py" ]; then
    cp "$Q5_APP/Contents/Resources/main.py" "$ZEST_DIR/"
    MAIN_PY_FOUND=true
fi

if $MAIN_PY_FOUND; then
    echo "✅ Standalone CLI installed"
else
    echo "⚠️  Could not find main.py in app bundle"
fi

# Create standalone wrapper in /usr/local/bin
echo ""
echo "📎 Setting up command-line access..."

WRAPPER_PATH="/usr/local/bin/zest"
cat > "$WRAPPER_PATH.tmp" << 'WRAPPER_EOF'
#!/bin/bash

# Zest CLI Wrapper - Survives app deletion for cleanup
# This standalone script can run even if the app bundle is deleted

FP16_APP="/Applications/Zest-FP16.app"
Q5_APP="/Applications/Zest-Q5.app"

# Find which app to use
if [ -d "$FP16_APP" ] && [ -d "$Q5_APP" ]; then
    # Both installed - check user preference
    CONFIG_FILE="$HOME/Library/Application Support/Zest/config.json"
    if [ -f "$CONFIG_FILE" ]; then
        ACTIVE=$(grep -o '"active_product": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | cut -d'"' -f4)
        [ "$ACTIVE" = "fp16" ] && APP_PATH="$FP16_APP" || APP_PATH="$Q5_APP"
    else
        APP_PATH="$FP16_APP"  # Default to FP16
    fi
elif [ -d "$FP16_APP" ]; then
    APP_PATH="$FP16_APP"
elif [ -d "$Q5_APP" ]; then
    APP_PATH="$Q5_APP"
else
    # No apps found - try standalone Python CLI for cleanup
    PYTHON_CLI="$HOME/.zest/main.py"
    if [ -f "$PYTHON_CLI" ]; then
        exec python3 "$PYTHON_CLI" "$@"
    else
        echo "❌ Zest is not installed."
        echo "   Install Zest-FP16.app or Zest-Q5.app to /Applications"
        exit 1
    fi
fi

# Run the app's launcher
exec "$APP_PATH/Contents/MacOS/zest-launcher" "$@"
WRAPPER_EOF

if [ -w /usr/local/bin ]; then
    mv "$WRAPPER_PATH.tmp" "$WRAPPER_PATH"
    chmod +x "$WRAPPER_PATH"
    echo "✅ Created wrapper: /usr/local/bin/zest"
else
    echo "   Creating wrapper requires administrator privileges."
    sudo mv "$WRAPPER_PATH.tmp" "$WRAPPER_PATH"
    sudo chmod +x "$WRAPPER_PATH"
    echo "✅ Created wrapper: /usr/local/bin/zest"
fi

# Detect shell and add alias
SHELL_NAME=$(basename "$SHELL")
SHELL_RC=""

case "$SHELL_NAME" in
    zsh)
        SHELL_RC="$HOME/.zshrc"
        ;;
    bash)
        if [ -f "$HOME/.bash_profile" ]; then
            SHELL_RC="$HOME/.bash_profile"
        else
            SHELL_RC="$HOME/.bashrc"
        fi
        ;;
esac

if [ -n "$SHELL_RC" ]; then
    echo ""
    echo "📝 Setting up shell aliases..."

    # Check if alias already exists
    if grep -q "alias zest=" "$SHELL_RC" 2>/dev/null; then
        echo "✅ Alias already configured in $SHELL_RC"
    else
        echo "" >> "$SHELL_RC"
        echo "# Zest CLI - Natural language to CLI commands" >> "$SHELL_RC"
        echo "alias zest='noglob zest'" >> "$SHELL_RC"
        echo "✅ Added alias to $SHELL_RC"
    fi
fi

echo ""
echo "🎉 Installation complete!"
echo ""
echo "Getting started:"
echo "  1. Open a new terminal window"
echo "  2. Run: zest \"your query here\""
echo "  3. Enter your purchase email when prompted"
echo ""
echo "Examples:"
echo "  zest \"find all python files modified today\""
echo "  zest \"show disk usage by folder\""
echo "  zest \"list all running processes\""
echo ""
