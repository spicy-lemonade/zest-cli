# IAM Groups and Permissions

# DEV PROJECT PERMISSIONS
# Project owner - Dev
resource "google_project_iam_member" "project_owner_dev" {
  project = var.project_id_dev
  role    = "roles/owner"
  member  = "user:${var.owner_email}"
}

# ML Engineers group - Editor access - Dev
resource "google_project_iam_member" "ml_engineers_editor_dev" {
  project = var.project_id_dev
  role    = "roles/editor"
  member  = "group:${var.ml_group_email}"
}

# Firestore/Datastore permissions for owner - Dev
resource "google_project_iam_member" "owner_datastore_dev" {
  project = var.project_id_dev
  role    = "roles/datastore.owner"
  member  = "user:${var.owner_email}"
}

# Firestore/Datastore permissions for ML engineers - Dev
resource "google_project_iam_member" "ml_engineers_datastore_dev" {
  project = var.project_id_dev
  role    = "roles/datastore.user"
  member  = "group:${var.ml_group_email}"
}

# PROD PROJECT PERMISSIONS
# Project owner - Prod
resource "google_project_iam_member" "project_owner_prod" {
  project = var.project_id_prod
  role    = "roles/owner"
  member  = "user:${var.owner_email}"
}

# Storage admin access - Prod
resource "google_project_iam_member" "admin_group_prod" {
  project = var.project_id_prod
  role    = "roles/storage.admin"
  member  = "user:${var.owner_email}"
}

# ML Engineers group - Editor access - Prod
resource "google_project_iam_member" "ml_engineers_editor_prod" {
  project = var.project_id_prod
  role    = "roles/editor"
  member  = "group:${var.ml_group_email}"
}

# Firestore/Datastore permissions for owner - Prod
resource "google_project_iam_member" "owner_datastore_prod" {
  project = var.project_id_prod
  role    = "roles/datastore.owner"
  member  = "user:${var.owner_email}"
}

# Firestore/Datastore permissions for ML engineers - Prod
resource "google_project_iam_member" "ml_engineers_datastore_prod" {
  project = var.project_id_prod
  role    = "roles/datastore.user"
  member  = "group:${var.ml_group_email}"
}

# SERVICE ACCOUNTS FOR CLOUD FUNCTIONS

# DEV PROJECT - Cloud Functions Service Account
resource "google_service_account" "cloud_functions_dev" {
  project      = var.project_id_dev
  account_id   = "cloud-functions-sa"
  display_name = "Cloud Functions Service Account"
  description  = "Service account for Cloud Functions with minimal Firestore permissions"
}

# Grant Firestore access to Cloud Functions service account - Dev
resource "google_project_iam_member" "cloud_functions_datastore_dev" {
  project = var.project_id_dev
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.cloud_functions_dev.email}"
}

# PROD PROJECT - Cloud Functions Service Account
resource "google_service_account" "cloud_functions_prod" {
  project      = var.project_id_prod
  account_id   = "cloud-functions-sa"
  display_name = "Cloud Functions Service Account"
  description  = "Service account for Cloud Functions with minimal Firestore permissions"
}

# Grant Firestore access to Cloud Functions service account - Prod
resource "google_project_iam_member" "cloud_functions_datastore_prod" {
  project = var.project_id_prod
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.cloud_functions_prod.email}"
}
