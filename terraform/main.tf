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
  name          = "nlcli-terraform-state-${var.project_id}"
  location      = var.region
  storage_class = "STANDARD"
  project       = var.project_id

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
  project       = var.project_id

  uniform_bucket_level_access = true

  versioning {
    enabled = var.enable_versioning
  }

  dynamic "lifecycle_rule" {
    for_each = var.data_retention_days > 0 ? [1] : []
    content {
      condition {
        age = var.data_retention_days
      }
      action {
        type = "Delete"
      }
    }
  }

  dynamic "lifecycle_rule" {
    for_each = var.enable_versioning ? [1] : []
    content {
      condition {
        num_newer_versions = 3
        with_state         = "ARCHIVED"
      }
      action {
        type = "Delete"
      }
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
  project       = var.project_id

  uniform_bucket_level_access = true

  versioning {
    enabled = var.enable_versioning
  }

  dynamic "lifecycle_rule" {
    for_each = var.data_retention_days > 0 ? [1] : []
    content {
      condition {
        age = var.data_retention_days
      }
      action {
        type = "Delete"
      }
    }
  }

  dynamic "lifecycle_rule" {
    for_each = var.enable_versioning ? [1] : []
    content {
      condition {
        num_newer_versions = 3
        with_state         = "ARCHIVED"
      }
      action {
        type = "Delete"
      }
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
  project       = var.project_id

  uniform_bucket_level_access = true

  versioning {
    enabled = var.enable_versioning
  }

  dynamic "lifecycle_rule" {
    for_each = var.data_retention_days > 0 ? [1] : []
    content {
      condition {
        age = var.data_retention_days
      }
      action {
        type = "Delete"
      }
    }
  }

  dynamic "lifecycle_rule" {
    for_each = var.enable_versioning ? [1] : []
    content {
      condition {
        num_newer_versions = 3
        with_state         = "ARCHIVED"
      }
      action {
        type = "Delete"
      }
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
  location      = var.region
  storage_class = "STANDARD"
  project       = var.project_id

  uniform_bucket_level_access = true

  versioning {
    enabled = false
  }

  labels = {
    environment = var.environment
    project     = "nlcli-wizard"
    purpose     = "ml-models"
  }
}
