terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  backend "gcs" {
    bucket = "nlcli-terraform-state-nl-cli"
    prefix = "nlcli-wizard/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
