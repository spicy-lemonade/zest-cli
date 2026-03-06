# 🌶️ Zest CLI from Spicy Lemonade 🍋

### Small language models. Runs offline. Runs on CPU. No cloud. No API keys. Privacy first. No tracking.

Zest CLI translates natural language into shell commands using local small language models. macOS only. Learn more at [zestcli.com](https://zestcli.com). 

![preview_zest](https://github.com/user-attachments/assets/932654b9-55a9-419a-82ff-3970606bbb9e)

## 🚀 Beyond the Basics
While the GIF shows simple file management, Zest is designed for a variety of domains:

- Networking: "Show all active listening TCP ports"
- Docker: "Show the logs for the Docker container `my-app`"
- Git: "Show the most recent commit that modified the file components/pages/AboutPage.tsx"
- System: "Check my disk usage and sort the top 5 largest directories in my home folder"

*Note: Zest works best with single requests. i.e. `show the top 5 XXX` is better than `show the top 5 XXX or YYY`*

### Why Zest CLI?

- **Small language models** — purpose-trained SLMs optimised for CLI command translation
- **Runs offline** — runs entirely on your machine with no network calls at inference time
- **Runs on CPU** — no GPU needed, works on any modern Mac
- **No cloud** — no cloud dependencies at inference time
- **No API keys** — no accounts, tokens, or subscriptions required
- **Privacy first** — your commands and queries never leave your device
- **No tracking** — zero telemetry, user data, or usage data collection

## 🏗 Architecture & Data Flow

While the core agent runs **offline on CPU** (privacy-first, no tracking), the training pipeline utilizes Google Cloud Storage (GCS) to manage datasets before they are loaded into Google Colab for fine-tuning.

The training data and data processing pipeline are maintained in a separate private repository. Both the data sources and the processing logic are confidential.

We utilize a **Medallion Architecture** pattern for data storage to ensure reproducibility and data quality:

| Layer | Bucket Role |
| :--- | :--- |
| **🥉 Base** | Raw input data (e.g., scraped CLI datasets, raw command data, synthetic data). |
| **🥈 Staging** | Intermediate processing; cleaned and deduplicated data. |
| **🥇 Mart** | Final training-formatted datasets with cross-dataset deduplication. |
| **🪣 Models** | Storage for final models. |

All training data buckets have versioning enabled (keeping 1 previous version). See [docs/model_releases.md](docs/model_releases.md) for details on model storage and release operations.

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
* **GitHub Pages:**
  * Free tier hosting on GitHub Pages. This needs the frontend repo to be public.
* **Zoho Mail:**
  * **Email Hosting:** Custom-domain email for internal and operational communication.
* **Resend:**
  * **Transactional Email:** Reliable delivery for product emails (auth, notifications, receipts).
* **Polar.sh:**
  * **Payments & Checkout:** Subscription management and checkout flow for monetization.


New developers must be onboarded with IAM permissions and API keys before working with this infrastructure. See [docs/setup.md](docs/setup.md) for setup, deployment, IAM, and secrets configuration.

![spicy](https://github.com/user-attachments/assets/9c3d925d-5c7b-44ed-a2c8-b73e5a897895)

