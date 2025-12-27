#!/usr/bin/env python3
"""
Create a test license in Firebase dev for testing the Zest CLI.
This script creates a license document in Firestore with is_paid=True.
"""
import sys
from firebase_admin import initialize_app, firestore, credentials

def create_test_license(email):
    """Create a test license in Firestore for the given email."""

    # Initialize Firebase Admin SDK
    # This uses the default credentials from the environment
    try:
        initialize_app()
    except ValueError:
        # App already initialized
        pass

    db = firestore.client()

    # Create the license document
    license_ref = db.collection("licenses").document(email)

    # Check if license already exists
    doc = license_ref.get()
    if doc.exists:
        print(f"⚠️  License already exists for {email}")
        print(f"Current data: {doc.to_dict()}")

        response = input("\nDo you want to reset it? [y/n]: ").strip().lower()
        if response != "y":
            print("Cancelled.")
            return

    # Create/update the license
    license_ref.set({
        "is_paid": True,
        "devices": []
    }, merge=False)

    print(f"✅ Test license created for: {email}")
    print(f"\nNext steps:")
    print(f"  1. Run the CLI: python main.py --help")
    print(f"  2. Enter email: {email}")
    print(f"  3. Check your email for the OTP code")
    print(f"  4. Verify device registration in Firebase console:")
    print(f"     https://console.firebase.google.com/project/nl-cli-dev/firestore/data/licenses/{email}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python create_test_license.py <email>")
        print("Example: python create_test_license.py test@example.com")
        sys.exit(1)

    email = sys.argv[1]

    print(f"🧪 Creating test license in Firebase dev")
    print(f"Email: {email}")
    print(f"Project: nl-cli-dev")
    print()

    # Make sure we're using the dev project
    print("⚠️  IMPORTANT: Make sure you're using the dev Firebase project:")
    print("   Run: firebase use dev")
    print()

    response = input("Continue? [y/n]: ").strip().lower()
    if response != "y":
        print("Cancelled.")
        sys.exit(0)

    create_test_license(email)
