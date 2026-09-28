#!/usr/bin/env python3
"""
Create a test license in Firestore for testing the Zest CLI.
Run this from the functions directory after setting up Firebase credentials.

Usage:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
    python create_test_license.py test@example.com
"""

import sys
import uuid
from datetime import datetime, timezone

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    print("Error: firebase-admin not installed.")
    print("Run: pip install firebase-admin")
    sys.exit(1)


def create_test_license(email: str):
    """Create a test license for the given email."""

    # Initialize Firebase Admin SDK
    try:
        firebase_admin.get_app()
    except ValueError:
        # Use default credentials (from GOOGLE_APPLICATION_CREDENTIALS env var)
        firebase_admin.initialize_app()

    db = firestore.client()

    # Build the license document
    now = datetime.now(timezone.utc)

    license_data = {
        "zest_user_id": str(uuid.uuid4()),
        "email": email,
        "updated_at": now.isoformat(),
        "updated_at_unix": int(now.timestamp()),
        "is_paid": True,
        "devices": [],
        "polar_order_id": "test_order_" + str(uuid.uuid4())[:8],
    }

    # Create/update the license document
    license_ref = db.collection("licenses").document(email)
    license_ref.set(license_data, merge=True)

    print(f"✅ Test license created for {email}")
    print(f"   Document ID: {email}")
    print(f"   Zest User ID: {license_data['zest_user_id']}")
    print("")
    print("Now you can run:")
    print(f"   zest \"your query\"")
    print("And enter this email when prompted for activation.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python create_test_license.py <email>")
        sys.exit(1)

    email = sys.argv[1]

    create_test_license(email)
