resource "google_secret_manager_secret" "app" {
  for_each = var.secret_names

  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}
