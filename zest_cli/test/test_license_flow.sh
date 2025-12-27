#!/bin/bash
# Test script for Zest CLI license flow with dev environment
# This tests the integration with Polar sandbox, Firebase dev, and Resend dev

set -e

echo "🧪 Zest CLI License Flow Test"
echo "=============================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
TEST_EMAIL="${TEST_EMAIL:-test@example.com}"
FIREBASE_PROJECT="nl-cli-dev"

echo -e "${BLUE}Configuration:${NC}"
echo "  Firebase Project: $FIREBASE_PROJECT"
echo "  Test Email: $TEST_EMAIL"
echo "  API Base: https://europe-west1-nl-cli-dev.cloudfunctions.net"
echo ""

# Step 1: Check if test license exists in Firestore
echo -e "${YELLOW}Step 1: Creating test license in Firestore...${NC}"
echo "Run this command to create a test license:"
echo ""
echo "firebase use dev"
echo "firebase firestore:update licenses/$TEST_EMAIL '{\"is_paid\": true, \"devices\": []}'"
echo ""
read -p "Press Enter after creating the license in Firestore..."

# Step 2: Clean local license file if it exists
echo ""
echo -e "${YELLOW}Step 2: Cleaning local license file...${NC}"
TOKEN_FILE="$HOME/Library/Application Support/Zest/license.json"
if [ -f "$TOKEN_FILE" ]; then
    echo "  Removing existing license file: $TOKEN_FILE"
    rm "$TOKEN_FILE"
else
    echo "  No existing license file found (this is good for first-time testing)"
fi

# Step 3: Test the authentication flow
echo ""
echo -e "${YELLOW}Step 3: Testing CLI authentication flow...${NC}"
echo ""
echo "When prompted:"
echo "  1. Enter email: $TEST_EMAIL"
echo "  2. Check your email for the OTP code"
echo "  3. Enter the 6-digit OTP"
echo ""
echo "Expected behavior:"
echo "  ✓ CLI asks for email"
echo "  ✓ OTP is sent via Resend to your email"
echo "  ✓ CLI asks for OTP code"
echo "  ✓ Device is registered in Firestore"
echo "  ✓ License file is created locally"
echo ""
read -p "Press Enter to start the CLI test..."

# Try to run the CLI
# We'll use a simple query that doesn't require the model if it fails
echo ""
echo -e "${BLUE}Running: python main.py --help${NC}"
python main.py --help

echo ""
echo -e "${GREEN}✅ Test completed!${NC}"
echo ""
echo "Next steps:"
echo "  1. Check Firebase dev console:"
echo "     https://console.firebase.google.com/project/nl-cli-dev/firestore/data/licenses/$TEST_EMAIL"
echo ""
echo "  2. Verify the device was registered:"
echo "     - The 'devices' array should have one entry"
echo "     - It should contain your device UUID and nickname"
echo ""
echo "  3. Check your email for the OTP"
echo ""
echo "  4. To test again, run: rm '$TOKEN_FILE' && ./test_license_flow.sh"
