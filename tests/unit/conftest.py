#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from collections import defaultdict
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml
from ops.pebble import ServiceStatus
from ops.testing import Container, Context, Resource, State
from src.charm import ConnectCharm
from src.literals import CONTAINER, PLUGIN_RESOURCE_KEY, SERVICE_NAME, SNAP_NAME, SUBSTRATE

CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def base_state():
    if SUBSTRATE == "k8s":
        state = State(
            leader=True,
            containers=[
                Container(
                    name=CONTAINER,
                    can_connect=True,
                    service_statuses={SERVICE_NAME: ServiceStatus.ACTIVE},
                )
            ],
        )
    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(ConnectCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


@pytest.fixture(autouse=True)
def patched_workload_write():
    with patch("workload.Workload.write") as workload_write:
        yield workload_write


@pytest.fixture(autouse=True)
def patched_exec():
    with patch("workload.Workload.exec") as patched_exec:
        yield patched_exec


@pytest.fixture(autouse=True)
def patched_remove():
    with patch("workload.Workload.remove") as patched_remove:
        yield patched_remove


@pytest.fixture(autouse=True)
def patched_ls():
    with patch("workload.Workload.ls") as patched_ls:
        yield patched_ls


@pytest.fixture(autouse=True)
def active_workload():
    with patch("workload.Workload.installed") as active_workload:
        yield active_workload


@pytest.fixture(autouse=True)
def patched_snap(monkeypatch):
    cache = Mock()
    snap_mock = Mock()
    snap_mock.services = defaultdict(default_factory=lambda _: {"active": True})
    cache.return_value = {SNAP_NAME: snap_mock}
    with monkeypatch.context() as m:
        m.setattr("charms.operator_libs_linux.v2.snap.SnapCache", cache)
        yield


@pytest.fixture(autouse=True)
def tenacity_wait():
    with patch("tenacity.nap.time") as patched_nap:
        yield patched_nap


@pytest.fixture(scope="module")
def kafka_client_rel():
    return {
        "username": "username",
        "password": "password",
        "tls": "disabled",
        "tls-ca": "disabled",
        "endpoints": "10.10.10.10:9092,10.10.10.11:9092",
    }


@pytest.fixture(scope="module")
def plugin_resource():
    return Resource(name=PLUGIN_RESOURCE_KEY, path="./tests/unit/resources/FakePlugin.tar")


@pytest.fixture(scope="module")
def active_service():
    with patch(
        "managers.connect.ConnectManager.health_check", return_value=True
    ) as patched_service:
        yield patched_service
