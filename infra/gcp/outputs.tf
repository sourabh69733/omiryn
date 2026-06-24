output "artifact_registry_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "database_url_socket_template" {
  value = "postgresql+psycopg://${var.sql_user_name}:<password>@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
}

output "cloud_run_service_account" {
  value = google_service_account.cloud_run.email
}

output "secret_names" {
  value = var.secret_names
}

output "cloud_run_url" {
  value = var.create_cloud_run_service ? google_cloud_run_v2_service.app[0].uri : null
}
