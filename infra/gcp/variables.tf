variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "Primary GCP region."
  type        = string
  default     = "asia-south1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "omiryn"
}

variable "artifact_repository" {
  description = "Artifact Registry repository for Docker images."
  type        = string
  default     = "omiryn"

  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]*[a-z0-9])?$", var.artifact_repository))
    error_message = "artifact_repository must be a repository id like omiryn, not a full registry URL."
  }
}

variable "sql_instance_name" {
  description = "Cloud SQL Postgres instance name."
  type        = string
  default     = "omiryn-postgres"
}

variable "sql_database_name" {
  description = "Application database name."
  type        = string
  default     = "omiryn"
}

variable "sql_user_name" {
  description = "Application database user."
  type        = string
  default     = "omiryn_app"
}

variable "sql_user_password" {
  description = "Database user password. Leave empty to skip Terraform-managed SQL user creation."
  type        = string
  sensitive   = true
  default     = ""
}

variable "sql_database_version" {
  description = "Cloud SQL Postgres version."
  type        = string
  default     = "POSTGRES_16"
}

variable "sql_edition" {
  description = "Cloud SQL edition. Use ENTERPRISE for small shared-core tiers like db-f1-micro."
  type        = string
  default     = "ENTERPRISE"
}

variable "sql_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-f1-micro"
}

variable "sql_disk_size_gb" {
  description = "Cloud SQL disk size in GB."
  type        = number
  default     = 10
}

variable "sql_public_ip_enabled" {
  description = "Enable public IPv4 on Cloud SQL. Keep true for the simple Cloud Run connector setup unless private connectivity is configured."
  type        = bool
  default     = true
}

variable "secret_names" {
  description = "Secret Manager secret names to create."
  type        = map(string)
  default = {
    database_url          = "omiryn-database-url"
    encryption_master_key = "omiryn-encryption-master-key"
    supabase_url          = "omiryn-supabase-url"
    supabase_anon_key     = "omiryn-supabase-anon-key"
    groq_api_key          = "omiryn-groq-api-key"
    openai_api_key        = "omiryn-openai-api-key"
  }
}

variable "create_cloud_run_service" {
  description = "Create Cloud Run service from Terraform. Keep false until you have pushed an image."
  type        = bool
  default     = false
}

variable "container_image" {
  description = "Container image used when create_cloud_run_service is true."
  type        = string
  default     = ""
}

variable "runtime_env" {
  description = "Non-secret Cloud Run environment variables."
  type        = map(string)
  default = {
    AUTH_PROVIDER              = "supabase"
    AUTH_REQUIRED              = "true"
    DB_DISABLE_POOL            = "true"
    AGENT_PROVIDER             = "mock"
    PROFILE_DEBUG_DATA_ENABLED = "false"
  }
}

variable "create_https_load_balancer" {
  description = "Create a global external HTTPS load balancer in front of Cloud Run."
  type        = bool
  default     = false
}

variable "load_balancer_domain_names" {
  description = "Custom domains for the managed SSL certificate, for example [\"app.example.com\"]."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for domain in var.load_balancer_domain_names :
      can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", domain))
    ])
    error_message = "load_balancer_domain_names must contain domain names only, without https:// or paths."
  }
}

variable "load_balancer_enable_cdn" {
  description = "Enable Cloud CDN on the Cloud Run backend service."
  type        = bool
  default     = true
}

variable "load_balancer_http_redirect" {
  description = "Create port 80 HTTP redirect to HTTPS."
  type        = bool
  default     = true
}
