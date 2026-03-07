output "base_bucket_name" {
  description = "Name of the base layer storage bucket"
  value       = google_storage_bucket.nlcli_ml_training_base.name
}

output "base_bucket_url" {
  description = "GCS URL of the base layer bucket"
  value       = google_storage_bucket.nlcli_ml_training_base.url
}

output "base_bucket_self_link" {
  description = "Self link of the base bucket for IAM bindings"
  value       = google_storage_bucket.nlcli_ml_training_base.self_link
}

output "staging_bucket_name" {
  description = "Name of the staging layer storage bucket"
  value       = google_storage_bucket.nlcli_ml_training_staging.name
}

output "staging_bucket_url" {
  description = "GCS URL of the staging layer bucket"
  value       = google_storage_bucket.nlcli_ml_training_staging.url
}

output "staging_bucket_self_link" {
  description = "Self link of the staging bucket for IAM bindings"
  value       = google_storage_bucket.nlcli_ml_training_staging.self_link
}

output "mart_bucket_name" {
  description = "Name of the mart layer storage bucket"
  value       = google_storage_bucket.nlcli_ml_training_mart.name
}

output "mart_bucket_url" {
  description = "GCS URL of the mart layer bucket"
  value       = google_storage_bucket.nlcli_ml_training_mart.url
}

output "mart_bucket_self_link" {
  description = "Self link of the mart bucket for IAM bindings"
  value       = google_storage_bucket.nlcli_ml_training_mart.self_link
}

output "firebase_dev_project_id" {
  description = "Firebase dev project ID"
  value       = var.project_id_dev
}

output "firebase_dev_project_number" {
  description = "Firebase dev project number"
  value       = google_firebase_project.dev.project_number
}

output "firestore_dev_database_name" {
  description = "Name of the Firestore dev database"
  value       = google_firestore_database.dev.name
}

output "firestore_dev_database_id" {
  description = "Fully qualified ID of the Firestore dev database"
  value       = google_firestore_database.dev.id
}

output "firebase_prod_project_id" {
  description = "Firebase prod project ID"
  value       = var.project_id_prod
}

output "firebase_prod_project_number" {
  description = "Firebase prod project number"
  value       = google_firebase_project.prod.project_number
}

output "firestore_prod_database_name" {
  description = "Name of the Firestore prod database"
  value       = google_firestore_database.prod.name
}

output "firestore_prod_database_id" {
  description = "Fully qualified ID of the Firestore prod database"
  value       = google_firestore_database.prod.id
}

output "models_bucket_name" {
  description = "Name of the models distribution bucket"
  value       = google_storage_bucket.nlcli_models.name
}

output "models_bucket_url" {
  description = "GCS URL of the models bucket"
  value       = google_storage_bucket.nlcli_models.url
}

output "models_https_url" {
  description = "HTTPS URL for the models bucket (requires signed URL or appropriate IAM for access)"
  value       = "https://storage.googleapis.com/${google_storage_bucket.nlcli_models.name}"
}

output "cloud_functions_service_account_dev" {
  description = "Service account email for Cloud Functions in dev environment"
  value       = google_service_account.cloud_functions_dev.email
}

output "cloud_functions_service_account_prod" {
  description = "Service account email for Cloud Functions in prod environment"
  value       = google_service_account.cloud_functions_prod.email
}
