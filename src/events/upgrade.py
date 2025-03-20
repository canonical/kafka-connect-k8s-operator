# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Connect in-place upgrades."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    EventBase,
    KubernetesClientError,
)
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.resources.apps_v1 import StatefulSet
from pydantic import BaseModel
from typing_extensions import override

if TYPE_CHECKING:
    from charm import ConnectCharm

logger = logging.getLogger(__name__)

ROLLBACK_INSTRUCTIONS = """Unit failed to upgrade and requires manual rollback to previous stable version.
    1. Re-run `pre-upgrade-check` action on the leader unit to enter 'recovery' state
    2. Run `juju refresh` to the previously deployed charm revision
"""


class ConnectDependencyModel(BaseModel):
    """Model for Connect Operator dependencies."""

    connect_service: DependencyModel


class ConnectUpgrade(DataUpgrade):
    """Implementation of :class:`DataUpgrade` overrides for in-place upgrades."""

    def __init__(self, charm: "ConnectCharm", **kwargs) -> None:
        super().__init__(charm, **kwargs)
        self.charm: "ConnectCharm" = charm
        self._connect_dependency_model: DependencyModel = getattr(
            self.dependency_model, "connect_service"
        )

        self.framework.observe(
            getattr(self.charm.on, "upgrade_charm"), self._on_kafka_pebble_ready_upgrade
        )

    def _on_kafka_pebble_ready_upgrade(self, event: EventBase) -> None:
        """Handler for the `upgrade-charm` events handled during in-place upgrades."""
        if not self.charm.workload.container.can_connect():
            event.defer()
            return

        # ensure pebble-ready only fires after normal peer-relation-driven server init
        if not self.charm.context.ready or self.idle:
            return

        # needed to run before setting config
        self.apply_backwards_compatibility_fixes(event)

        self.charm.reconcile()

        # start workload service
        self.charm.workload.start()

        try:
            self.post_upgrade_check()
        except ClusterNotReadyError as e:
            logger.error(e.cause)
            self.set_unit_failed()
            return

        self.set_unit_completed()

    @property
    def idle(self) -> bool:
        """Checks if cluster state is idle.

        Returns:
            True if cluster state is idle. Otherwise False
        """
        return not bool(self.upgrade_stack)

    @property
    def current_version(self) -> str:
        """Get current Kafka version."""
        return self._connect_dependency_model.version

    @override
    def pre_upgrade_check(self) -> None:
        default_message = "Pre-upgrade check failed and cannot safely upgrade"
        if not self.charm.connect_manager.health_check():
            raise ClusterNotReadyError(message=default_message, cause="Cluster is not healthy")

        if self.idle:
            self._set_rolling_update_partition(partition=len(self.charm.context.units) - 1)

    def post_upgrade_check(self) -> None:
        """Runs necessary checks validating the unit is in a healthy state after upgrade."""
        self.pre_upgrade_check()

    @override
    def log_rollback_instructions(self) -> None:
        logger.critical(ROLLBACK_INSTRUCTIONS)

    @override
    def _set_rolling_update_partition(self, partition: int) -> None:
        """Set the rolling update partition to a specific value."""
        try:
            patch = {"spec": {"updateStrategy": {"rollingUpdate": {"partition": partition}}}}
            Client().patch(  # pyright: ignore [reportArgumentType]
                StatefulSet,
                name=self.charm.model.app.name,
                namespace=self.charm.model.name,
                obj=patch,
            )
            logger.debug(f"Kubernetes StatefulSet partition set to {partition}")
        except ApiError as e:
            if e.status.code == 403:
                cause = "`juju trust` needed"
            else:
                cause = str(e)
            raise KubernetesClientError("Kubernetes StatefulSet patch failed", cause)

    def apply_backwards_compatibility_fixes(self, _: EventBase) -> None:
        """A range of functions needed for backwards compatibility."""
        logger.info("Applying upgrade fixes")
        return
