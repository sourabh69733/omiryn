locals {
  create_https_lb = var.create_https_load_balancer && length(var.load_balancer_domain_names) > 0
}

resource "google_compute_global_address" "app_lb" {
  count = local.create_https_lb ? 1 : 0

  name = "${var.service_name}-lb-ip"

  depends_on = [google_project_service.required]
}

resource "google_compute_managed_ssl_certificate" "app_lb" {
  count = local.create_https_lb ? 1 : 0

  name = "${var.service_name}-managed-cert"

  managed {
    domains = var.load_balancer_domain_names
  }

  depends_on = [google_project_service.required]
}

resource "google_compute_region_network_endpoint_group" "cloud_run" {
  count = local.create_https_lb ? 1 : 0

  name                  = "${var.service_name}-serverless-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  cloud_run {
    service = var.service_name
  }

  depends_on = [google_project_service.required]
}

resource "google_compute_backend_service" "app_lb" {
  count = local.create_https_lb ? 1 : 0

  name                  = "${var.service_name}-backend"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  enable_cdn            = var.load_balancer_enable_cdn

  backend {
    group = google_compute_region_network_endpoint_group.cloud_run[0].id
  }
}

resource "google_compute_url_map" "app_https" {
  count = local.create_https_lb ? 1 : 0

  name            = "${var.service_name}-https-map"
  default_service = google_compute_backend_service.app_lb[0].id
}

resource "google_compute_target_https_proxy" "app" {
  count = local.create_https_lb ? 1 : 0

  name             = "${var.service_name}-https-proxy"
  url_map          = google_compute_url_map.app_https[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.app_lb[0].id]
}

resource "google_compute_global_forwarding_rule" "app_https" {
  count = local.create_https_lb ? 1 : 0

  name                  = "${var.service_name}-https-rule"
  ip_address            = google_compute_global_address.app_lb[0].address
  ip_protocol           = "TCP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "443"
  target                = google_compute_target_https_proxy.app[0].id
}

resource "google_compute_url_map" "app_http_redirect" {
  count = local.create_https_lb && var.load_balancer_http_redirect ? 1 : 0

  name = "${var.service_name}-http-redirect-map"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "app_redirect" {
  count = local.create_https_lb && var.load_balancer_http_redirect ? 1 : 0

  name    = "${var.service_name}-http-redirect-proxy"
  url_map = google_compute_url_map.app_http_redirect[0].id
}

resource "google_compute_global_forwarding_rule" "app_http_redirect" {
  count = local.create_https_lb && var.load_balancer_http_redirect ? 1 : 0

  name                  = "${var.service_name}-http-redirect-rule"
  ip_address            = google_compute_global_address.app_lb[0].address
  ip_protocol           = "TCP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "80"
  target                = google_compute_target_http_proxy.app_redirect[0].id
}
