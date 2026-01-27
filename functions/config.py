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
MAX_DEVICES_PER_PRODUCT = 2
OTP_EXPIRY_MINUTES = 10
VALID_PRODUCTS = ["lite", "hot", "extra_spicy"]
TRIAL_DURATION_DAYS = 5

# Polar.sh product IDs (from sandbox dashboard)
POLAR_PRODUCT_IDS = {
    "lite": "1cb33873-4b44-4cda-83cb-511805e7f02c",
    "hot": "47d61b83-33f5-45b4-8543-66a4d1afe8d6",
    "extra_spicy": "8a5011a7-d888-4c3e-9086-bb1063f50b30",
}

# Model file configuration
MODEL_FILES = {
    "lite": "qwen3_4b_Q5_K_M.gguf",
    "hot": "qwen2_5_coder_7b_Q5_K_M.gguf",
    "extra_spicy": "qwen2_5_coder_7b_fp16.gguf"
}
GCS_BUCKET = "nlcli-models"
