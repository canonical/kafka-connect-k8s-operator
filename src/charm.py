#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka Connect."""

import datetime
import logging

import ops
from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops import (
    CollectStatusEvent,
    EventBase,
    InstallEvent,
    ModelError,
    StartEvent,
    StatusBase,
)

from core.models import Context
from core.structured_config import CharmConfig
from events.connect import ConnectHandler
from events.kafka import KafkaHandler
from events.tls import TLSHandler
from events.upgrade import ConnectDependencyModel, ConnectUpgrade
from events.user_secrets import SecretsHandler
from literals import (
    CHARM_KEY,
    CONTAINER,
    DEPENDENCIES,
    JMX_EXPORTER_PORT,
    METRICS_RULES_DIR,
    PLUGIN_RESOURCE_KEY,
    SUBSTRATE,
    LogLevel,
    Status,
    Substrates,
)
from managers.auth import AuthManager
from managers.config import ConfigManager
from managers.connect import ConnectManager
from managers.tls import TLSManager
from workload import Workload

logger = logging.getLogger(__name__)


class ConnectCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Apache Kafka Connect."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.substrate: Substrates = SUBSTRATE
        self.pending_inactive_statuses: list[Status] = []

        self.workload = Workload(
            container=self.unit.get_container(CONTAINER), profile=self.config.profile
        )
        self.context = Context(self, substrate=SUBSTRATE)
        self.auth_manager = AuthManager(
            context=self.context, workload=self.workload, store_path=self.workload.paths.passwords
        )
        self.config_manager = ConfigManager(
            context=self.context, workload=self.workload, config=self.config
        )
        self.connect_manager = ConnectManager(context=self.context, workload=self.workload)
        self.tls_manager = TLSManager(self.context, self.workload, substrate=SUBSTRATE)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        if self.substrate == "k8s":
            self.framework.observe(getattr(self.on, "kafka_connect_pebble_ready"), self._on_start)

        self.connect = ConnectHandler(self)
        self.kafka = KafkaHandler(self)
        self.tls = TLSHandler(self)
        self.upgrade = ConnectUpgrade(
            self,
            substrate=self.substrate,
            dependency_model=ConnectDependencyModel(
                **DEPENDENCIES  # pyright: ignore[reportArgumentType]
            ),
        )

        self.user_secrets = SecretsHandler(self)

        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart_callback)

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [
                        {
                            "targets": [
                                f"*:{JMX_EXPORTER_PORT}",
                            ]
                        }
                    ]
                }
            ],
            alert_rules_path=METRICS_RULES_DIR,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.loki_push = LogProxyConsumer(
            self,
            log_files=[
                f"{self.workload.paths.logs_dir}/connect.log",
            ],
            relation_name="logging",
            container_name=CONTAINER,
        )

    def _on_install(self, event: InstallEvent) -> None:
        """Handler for `install` event."""
        if not self.workload.container_can_connect:
            event.defer()
            return

    def _on_start(self, event: StartEvent) -> None:
        if not self.workload.container_can_connect:
            event.defer()
            return

        if not self.context.kafka_client.relation:
            self._set_status(Status.MISSING_KAFKA)

    def _on_remove(self, _) -> None:
        """Handler for `stop` event."""
        self.workload.stop()

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: LogLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.pending_inactive_statuses.append(key)

    def _on_collect_status(self, event: CollectStatusEvent):
        """Handler for `collect-status` event."""
        workload_status = Status.INSTALLING if not self.workload.installed else self.context.status
        for status in self.pending_inactive_statuses + [workload_status]:
            event.add_status(status.value.status)

    def _restart_callback(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        if not self.context.ready or not self.context.worker_unit.should_restart:
            return

        self.connect_manager.restart_worker()

        for _ in range(4):
            # shouldn't take longer than a minute
            if self.connect_manager.health_check():
                self.context.worker_unit.should_restart = False
                return

    def reconcile(self) -> None:
        """Substrate-agnostic method for startup/restarts/config-changes which orchestrates workload, managers and handlers.

        This method is safe to call and only triggers a workload restart if necessary.
        """
        if not self.connect_manager.plugin_path_initiated:
            self.connect_manager.init_plugin_path()

        try:
            resource_path = self.model.resources.fetch(PLUGIN_RESOURCE_KEY)
            self.connect_manager.load_plugin(resource_path)
        except RuntimeError:
            logger.error(f"Resource {PLUGIN_RESOURCE_KEY} not defined in the charm build.")
        except (NameError, ModelError):
            logger.debug(
                f"Resource {PLUGIN_RESOURCE_KEY} not found or could not be downloaded, skipping plugin loading."
            )

        self.connect.update_plugins()
        self.connect.update_clients_data()

        # Check if SANs have changed.
        if self.context.peer_workers.tls_enabled and self.tls_manager.sans_change_detected:
            unit_tls_context = self.context.worker_unit.tls
            self.tls.certificates.on.certificate_expiring.emit(
                certificate=unit_tls_context.certificate,
                expiry=datetime.datetime.now().isoformat(),
            )
            self.context.worker_unit.update(
                {unit_tls_context.CERT: ""}
            )  # ensures only single requested new certs, will be replaced on new certificate-available event

            return  # config-changed would be eventually fired on certificate-available, so no need to defer.

        current_config = set(self.workload.read(self.workload.paths.worker_properties))
        diff = set(self.config_manager.properties) ^ current_config

        if diff:
            self.context.worker_unit.should_restart = True

        if not self.context.worker_unit.should_restart:
            return

        if not self.context.ready:
            self._set_status(self.context.status)
            return

        self.connect.enable_auth()
        self.tls_manager.configure()
        self.config_manager.configure()

        self.on[f"{self.restart.name}"].acquire_lock.emit()


if __name__ == "__main__":
    ops.main(ConnectCharm)  # pyright: ignore[reportCallIssue]
