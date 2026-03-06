locals {
  bucket_suffix       = var.bucket_suffix != "" ? var.bucket_suffix : random_id.bucket_suffix[0].hex
  bucket_name_base    = "nlcli-ml-training-base-${local.bucket_suffix}"
  bucket_name_staging = "nlcli-ml-training-staging-${local.bucket_suffix}"
  bucket_name_mart    = "nlcli-ml-training-mart-${local.bucket_suffix}"
}

resource "random_id" "bucket_suffix" {
  count       = var.bucket_suffix == "" ? 1 : 0
  byte_length = 4
}

resource "google_storage_bucket" "terraform_state" {
  name          = "nlcli-terraform-state-${var.project_id_prod}"
  location      = var.region
  storage_class = "STANDARD"
  project       = var.project_id_prod

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  labels = {
    environment = var.environment
    project     = "nlcli-wizard"
    purpose     = "terraform-state"
  }
}

resource "google_storage_bucket" "nlcli_ml_training_base" {
  name          = local.bucket_name_base
  location      = var.region
  storage_class = "STANDARD"
  project       = var.project_id_prod

  uniform_bucket_level_access = true

  versioning {
    enabled = var.enable_versioning
  }

  # Move current objects to COLDLINE after 14 days
  lifecycle_rule {
    condition {
      age                   = 14
      matches_storage_class = ["STANDARD"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  # Move non-current versions to COLDLINE after 14 days
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 14
      matches_storage_class      = ["STANDARD"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  # Keep only 1 most recent version
  lifecycle_rule {
    condition {
      num_newer_versions = 1
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment  = var.environment
    project      = "nlcli-wizard"
    data_layer   = "base"
    architecture = "medallion"
    purpose      = "ml-training"
  }
}

resource "google_storage_bucket" "nlcli_ml_training_staging" {
  name          = local.bucket_name_staging
  location      = var.region
  storage_class = "STANDARD"
  project       = var.project_id_prod

  uniform_bucket_level_access = true

  versioning {
    enabled = var.enable_versioning
  }

  # Keep only 1 most recent version
  lifecycle_rule {
    condition {
      num_newer_versions = 1
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment  = var.environment
    project      = "nlcli-wizard"
    data_layer   = "staging"
    architecture = "medallion"
    purpose      = "ml-training"
  }
}

resource "google_storage_bucket" "nlcli_ml_training_mart" {
  name          = local.bucket_name_mart
  location      = var.region
  storage_class = "STANDARD"
  project       = var.project_id_prod

  uniform_bucket_level_access = true

  versioning {
    enabled = var.enable_versioning
  }

  # Keep only 1 most recent version
  lifecycle_rule {
    condition {
      num_newer_versions = 1
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment  = var.environment
    project      = "nlcli-wizard"
    data_layer   = "mart"
    architecture = "medallion"
    purpose      = "ml-training"
  }
}

resource "google_storage_bucket" "nlcli_models" {
  name          = "nlcli-models"
  location      = "US"  # Multi-region for fast global downloads (US has best global latency)
  storage_class = "STANDARD"
  project       = var.project_id_prod
  force_destroy = true  # Allow deletion even with objects (for migration)

  uniform_bucket_level_access = true

  versioning {
    enabled = true  # Keep old model versions for rollback
  }

  # Keep only 1 previous version for rollback (current + 1 old)
  lifecycle_rule {
    condition {
      num_newer_versions = 1
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = var.environment
    project     = "nlcli-wizard"
    purpose     = "ml-models-distribution"
  }
}

resource "google_storage_bucket" "nlcli_downloads" {
  name          = "nlcli-downloads"
  location      = "US"
  storage_class = "STANDARD"
  project       = var.project_id_prod

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  # Keep only 1 previous version for rollback (current + 1 old)
  lifecycle_rule {
    condition {
      num_newer_versions = 1
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = var.environment
    project     = "nlcli-wizard"
    purpose     = "dmg-distribution"
  }
}

resource "google_storage_bucket_iam_member" "nlcli_downloads_public_read" {
  bucket = google_storage_bucket.nlcli_downloads.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

