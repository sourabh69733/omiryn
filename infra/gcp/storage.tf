locals {
  profile_photo_bucket_name = var.profile_photo_bucket_name != "" ? var.profile_photo_bucket_name : "${var.project_id}-${var.service_name}-profile-photos"
}

resource "google_storage_bucket" "profile_photos" {
  name                        = local.profile_photo_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true

  cors {
    origin          = ["*"]
    method          = ["GET", "HEAD"]
    response_header = ["Content-Type"]
    max_age_seconds = 3600
  }
}

resource "google_storage_bucket_iam_member" "cloud_run_profile_photo_writer" {
  bucket = google_storage_bucket.profile_photos.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_storage_bucket_iam_member" "public_profile_photo_viewer" {
  count = var.profile_photo_bucket_public_read ? 1 : 0

  bucket = google_storage_bucket.profile_photos.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
