"""
Shared configuration constants for Zest CLI cloud functions.
"""

import os

# Service account configuration
# Automatically construct the service account email from the project ID
# The service account is created by Terraform as "cloud-functions-sa"
_project_id = os.environ.get("GCLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
SERVICE_ACCOUNT_EMAIL = f"cloud-functions-sa@{_project_id}.iam.gserviceaccount.com" if _project_id else None

# License configuration
MAX_DEVICES = 2
OTP_EXPIRY_MINUTES = 10
TRIAL_DURATION_DAYS = 5
MAX_OTP_SENDS_PER_HOUR = 5
MAX_OTP_VERIFY_ATTEMPTS = 5

# Polar.sh product ID (set via functions/.env.<project-id>)
POLAR_PRODUCT_ID = os.environ.get("POLAR_PRODUCT_ID", "")

# Model file configuration
MODEL_FILE = "qwen3.5_9b_Q5_K_M.gguf"
GCS_BUCKET = os.environ.get("GCS_BUCKET", "nlcli-models")
