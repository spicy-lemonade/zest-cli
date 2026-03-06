terraform {
  backend "gcs" {
    bucket = "nlcli-terraform-state-nl-cli"
    prefix = "nlcli-wizard/state"
  }
}
