resource "juju_application" "connect" {
  model = var.model
  name  = var.app_name

  charm {
    name     = "kafka-connect-k8s"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  units       = var.units
  constraints = var.constraints
  config      = var.config
  trust       = true
}

resource "juju_offer" "connect_client" {
  model            = var.model
  application_name = juju_application.connect.name
  endpoints        = ["connect-client"]
}
