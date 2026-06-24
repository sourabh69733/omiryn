data "google_project" "current" {
  project_id = var.project_id
}

locals {
  cloud_build_service_accounts = toset([
    "${data.google_project.current.number}@cloudbuild.gserviceaccount.com",
    "${data.google_project.current.number}-compute@developer.gserviceaccount.com",
  ])
}

resource "google_service_account" "cloud_run" {
  account_id   = "${var.service_name}-run"
  display_name = "Omiryn Cloud Run runtime"
}

resource "google_project_iam_member" "cloud_build_storage_viewer" {
  for_each = local.cloud_build_service_accounts

  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "cloud_build_artifact_writer" {
  for_each = local.cloud_build_service_accounts

  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "cloud_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_secret_manager_secret_iam_member" "cloud_run_secret_access" {
  for_each = google_secret_manager_secret.app

  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}
