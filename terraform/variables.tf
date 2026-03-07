variable "project_id_dev" {
  description = "GCP project ID for dev environment (set in terraform.tfvars)"
  type        = string
}

variable "project_id_prod" {
  description = "GCP project ID for prod environment (set in terraform.tfvars)"
  type        = string
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "europe-west1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "bucket_suffix" {
  description = "Optional suffix for bucket name uniqueness (leave empty for auto-generated)"
  type        = string
  default     = ""
}

variable "data_retention_days" {
  description = "Number of days to retain data before lifecycle deletion (0 = no deletion)"
  type        = number
  default     = 0
}

variable "enable_versioning" {
  description = "Enable object versioning on the bucket"
  type        = bool
  default     = true
}

variable "owner_email" {
  description = "Email address of the project owner (set in terraform.tfvars)"
  type        = string
}

variable "ml_group_email" {
  description = "Google Group email for ML engineers (set in terraform.tfvars)"
  type        = string
}

variable "models_bucket_name" {
  description = "Name of the GCS bucket for model files (set in terraform.tfvars)"
  type        = string
}

variable "downloads_bucket_name" {
  description = "Name of the GCS bucket for DMG downloads (set in terraform.tfvars)"
  type        = string
}
