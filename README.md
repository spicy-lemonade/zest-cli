# Zest CLI - Infra

#### Using locally-trained small language models. No cloud. No API keys. Runs offline. Runs on CPU. Privacy first. No tracking. No Logging. No analytics.
![spicy](https://github.com/user-attachments/assets/9c3d925d-5c7b-44ed-a2c8-b73e5a897895)

## 🏗 Architecture & Data Flow

While the core agent runs **offline on CPU** (privacy-first, no tracking), the training pipeline utilizes Google Cloud Storage (GCS) to manage datasets before they are loaded into Google Colab for fine-tuning.

We utilize a **Medallion Architecture** pattern for data storage to ensure reproducibility and data quality:

| Layer | Bucket Role | Description |
| :--- | :--- | :--- |
| **🥉 Base** | `nlcli-ml-training-base-03ca945a` | Raw input data (e.g., scraped CLI help docs, raw command logs). |
| **🥈 Staging** | `nlcli-ml-training-staging-03ca945a` | Cleaned and deduplicated data (per dataset deduplication); intermediate processing. |
| **🥇 Mart** | `nlcli-ml-training-mart-03ca945a` | Final datasets training with deduplication (cross dataset deduplication). |
| **🪣 Models** | `nlcli-models` | Storage for final `.gguf` quantized models. We want to stay within the free tier (5GB) so use Hugging Face preferably.  |

### Versioning

  | Bucket  | Versioning | Version Cleanup | COLDLINE Transition                   |  
  |---------|------------|-----------------|---------------------------------------|
  | base    | Enabled    | Keep 3 versions | After 14 days (current + non-current) |     
  | staging | Enabled    | Keep 3 versions | None                                  |     
  | mart    | Enabled    | Keep 3 versions | None                                  |                                                                                                              
  | models  | None    | Keep 3 versions | None                                  | 

---

## 🛠 Tech Stack

* **Terraform:** State management and infrastructure provisioning across environments.
* **Google Cloud Platform (GCP):**
  * **Cloud Storage (GCS):** Persistent storage for training datasets and artifacts.
  * **IAM:** Role-based access control for engineering and operations teams.
  * **Cloud Billing:** Cost tracking and budget alerts via email.
* **Cloudflare:**
  * **DNS & Domain Management:** Domain `zestcli.com`, and DNS.
  * **Security & Performance:**  Website passed through cloudflare proxy
* ** Github Pages:**
  * Free tier hosting on Github Pages. This needs the frontend repo to be public however. 
* **Zoho Mail:**
  * **Email Hosting:** Custom-domain email for internal and operational communication.
* **Resend:**
  * **Transactional Email:** Reliable delivery for product emails (auth, notifications, receipts).
* **Polar.sh:**
  * **Payments & Checkout:** Subscription management and checkout flow for monetization.

---

## 🚀 Getting Started

### Prerequisites

1.  [Terraform CLI](https://developer.hashicorp.com/terraform/downloads) installed.
2.  [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed.

### Setup & Deployment

1.  **Authenticate with GCP:**
    ```bash
    gcloud auth application-default login
    ```

2.  **Initialize Terraform:**
    ```bash
    terraform init
    ```

3.  **Review the Plan:**
    ```bash
    terraform plan
    ```

4.  **Apply Changes:**
    ```bash
    terraform apply
    ```

---

## 🔐 IAM & Security

Access is managed via Google Groups to streamline permissions for the ML Engineering team.

* **Group:** `spicy-lemonage-nl-cli-ml-engineers@googlegroups.com`
* **Permissions:** Members of this group inherit read/write access to the storage buckets for ML and data work.

**To onboard a new engineer:**
1.  Add their email to the Google Group.
2.  Have them run the `gcloud` auth command listed in "Getting Started".

---

## 💰 Infra Breakdown - Cost Strategy

**Goal:** Near zero-cost infrastructure.

We intend to operate as close as possible to the **GCP Free Tier limits**:
* **Storage:** < 15GB-months of standard storage (~8gb full precision model, ~3gb quantised model, ~2gb data)
* **Compute:** ~€0 (Training occurs on Google Colab 'pay as you go; credits for GPUs).
* **Database:** Firebase free tier.
* **Synthetic data:** ~€0 Use `gemini-2.5-flash-lite` (used in the `natural-language-cli-eng` repo).
* **Domain:** ~€10 p/a for Cloudflare domain name `zestcli.com`
* **Email:** ~€10 p/a for Zoho email `info@zestcli.com`
* **Emailing:** ~€0 for 3000 transactional emails (for sending OTP when registering)
* **Claude:** €20 ongoing personal cost for Claude code

---

## Billing account
Ciaran currently owns the billing account under his personal email ciaranobrienmusic@gmail.com

---

## 🔑 Firebase Functions Secrets

The backend uses Firebase Cloud Functions with the following secrets:

### Polar.sh Payment Integration

1. **POLAR_ACCESS_TOKEN**: API token from Polar.sh dashboard
   ```bash
   firebase functions:secrets:set POLAR_ACCESS_TOKEN
   ```

2. **POLAR_WEBHOOK_SECRET**: Webhook signing secret from Polar.sh webhook settings
   ```bash
   firebase functions:secrets:set POLAR_WEBHOOK_SECRET
   ```

### Email Service (Resend)

3. **RESEND_API_KEY**: API key from Resend dashboard
   ```bash
   firebase functions:secrets:set RESEND_API_KEY
   ```

### Deployment

After setting secrets, deploy functions:
```bash
cd functions
firebase deploy --only functions
```

### Webhook Configuration

After deployment, configure this webhook URL in your Polar.sh dashboard:
```
https://europe-west1-<your-project-id>.cloudfunctions.net/polar_webhook
```

Enable the following webhook event:
- **order.created** (fires when a one-time purchase is completed) 

## 🤖 Test Install
After building the dmg you can open it from the repo via:

- Run `open ~/spicy_lemonade/natural-language-cli-infra/zest_cli/dist/Zest-Q5-1.0.0.dmg`
