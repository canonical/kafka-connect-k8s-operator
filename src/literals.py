#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of globals common to the Kafka Connect Charm."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, StatusBase, WaitingStatus

CHARM_KEY = "kafka-connect-k8s"
SNAP_NAME = "charmed-kafka"
CHARMED_KAFKA_SNAP_REVISION = "57"
CONTAINER = "kafka-connect"
SUBSTRATE = "k8s"

# '584788' refers to snap_daemon, which do not exists on the storage-attached hook prior to the
# snap install.
# FIXME (24.04): From snapd 2.61 onwards, snap_daemon is being deprecated and replaced with _daemon_,
# which now possesses a UID of 584792.
# See https://snapcraft.io/docs/system-usernames.
USER = "kafka"
GROUP = "kafka"

DEFAULT_API_PORT = 8083
DEFAULT_API_PROTOCOL = "http"
DEFAULT_AUTH_CLASS = (
    "org.apache.kafka.connect.rest.basic.auth.extension.BasicAuthSecurityRestExtension"
)
DEFAULT_CONVERTER_CLASS = "org.apache.kafka.connect.json.JsonConverter"
DEFAULT_SECURITY_MECHANISM = "SCRAM-SHA-512"
GROUP_ID = "connect-cluster"

SERVICE_NAME = "connect-distributed"
PLUGIN_RESOURCE_KEY = "connect-plugin"
PLUGIN_PATH = "/var/lib/connect/plugins/"
CONFIG_DIR = "/etc/connect"
JMX_EXPORTER_PORT = 9100
METRICS_RULES_DIR = "./src/alert_rules/prometheus"
EMPTY_PLUGIN_CHECKSUM = "84ff92691f909a05b224e1c56abb4864f01b4f8e3c854e4bb4c7baf1d3f6d652"

TOPICS = {"offset": "connect-offset", "config": "connect-config", "status": "connect-status"}
REPLICATION_FACTOR = -1  # -1 uses broker's default replication factor

# NOTE: This key is used on a file to set the truststore password. The mirrormaker integrator charm
# then points to this file to avoid sending the password over the API request config.
TRUSTSTORE_PASSWORD_KEY = "truststore"

# Relations
KAFKA_CLIENT_REL = "kafka-client"
PEER_REL = "worker"
CLIENT_REL = "connect-client"
TLS_REL = "certificates"

CharmProfile = Literal["testing", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
DatabagScope = Literal["unit", "app"]
Substrates = Literal["vm", "k8s"]
ClientModes = Literal["worker", "producer", "consumer"]
Converters = Literal["key", "value"]
InternalTopics = Literal["offset", "config", "status"]


@dataclass
class StatusLevel:
    """Status object helper."""

    status: StatusBase
    log_level: LogLevel


class Status(Enum):
    """Collection of possible statuses for the charm."""

    SNAP_NOT_INSTALLED = StatusLevel(BlockedStatus(f"unable to install {SNAP_NAME} snap"), "ERROR")
    INSTALLING = StatusLevel(MaintenanceStatus(f"Installing {SNAP_NAME}"), "DEBUG")
    MISSING_KAFKA = StatusLevel(BlockedStatus("Application needs Kafka client relation"), "DEBUG")
    NO_KAFKA_CREDENTIALS = StatusLevel(
        WaitingStatus("Waiting for Kafka cluster credentials"), "DEBUG"
    )
    SERVICE_NOT_RUNNING = StatusLevel(BlockedStatus("Worker service is not running"), "WARNING")

    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")


DEPENDENCIES = {
    "connect_service": {
        "dependencies": {},  # do not need to check Kafka, backwards compatible since 0.10
        "name": "connect",
        "upgrade_supported": "^3.9",
        "version": "3.9.0",
    },
}
