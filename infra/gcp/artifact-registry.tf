resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = var.artifact_repository
  description   = "Omiryn application Docker images"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}
