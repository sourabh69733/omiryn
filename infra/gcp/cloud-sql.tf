resource "google_sql_database_instance" "postgres" {
  name             = var.sql_instance_name
  database_version = var.sql_database_version
  region           = var.region

  deletion_protection = true

  settings {
    tier              = var.sql_tier
    availability_type = "ZONAL"
    disk_size         = var.sql_disk_size_gb
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled = false
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database" "app" {
  name     = var.sql_database_name
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app" {
  count = var.sql_user_password == "" ? 0 : 1

  name     = var.sql_user_name
  instance = google_sql_database_instance.postgres.name
  password = var.sql_user_password
}
