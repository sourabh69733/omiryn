locals {
  cloud_run_secret_env = {
    DATABASE_URL          = var.secret_names.database_url
    ENCRYPTION_MASTER_KEY = var.secret_names.encryption_master_key
    SUPABASE_URL          = var.secret_names.supabase_url
    SUPABASE_ANON_KEY     = var.secret_names.supabase_anon_key
    GROQ_API_KEY          = var.secret_names.groq_api_key
    OPENAI_API_KEY        = var.secret_names.openai_api_key
  }
}

resource "google_cloud_run_v2_service" "app" {
  count = var.create_cloud_run_service ? 1 : 0

  name                = var.service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.cloud_run.email

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }

    containers {
      image = var.container_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      dynamic "env" {
        for_each = var.runtime_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.cloud_run_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.cloud_run_secret_access,
    google_project_iam_member.cloud_sql_client,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = var.create_cloud_run_service ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
