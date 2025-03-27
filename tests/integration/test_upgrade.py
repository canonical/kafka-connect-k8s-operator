#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    APP_NAME,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    KAFKA_APP,
    KAFKA_CHANNEL,
    check_connect_endpoints_status,
)
from pytest_operator.plugin import OpsTest

from literals import DEFAULT_API_PORT

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.broker

CHANNEL = "edge"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_in_place_upgrade(ops_test: OpsTest, kafka_connect_charm):
    # deploy kafka & kafka-connect
    await asyncio.gather(
        ops_test.model.deploy(
            APP_NAME,
            channel=CHANNEL,
            application_name=APP_NAME,
            num_units=3,
            series="jammy",
            trust=True,
        ),
        ops_test.model.deploy(
            KAFKA_APP,
            channel=KAFKA_CHANNEL,
            application_name=KAFKA_APP,
            num_units=1,
            series="jammy",
            config={"roles": "broker,controller"},
        ),
    )

    await ops_test.model.wait_for_idle(apps=[APP_NAME, KAFKA_APP], timeout=3000)
    await ops_test.model.add_relation(APP_NAME, KAFKA_APP)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, KAFKA_APP], idle_period=60, timeout=1200, status="active"
        )

    leader_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check...")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=15, status="active"
    )

    logger.info("Upgrading Connect...")
    await ops_test.model.applications[APP_NAME].refresh(
        path=kafka_connect_charm,
        resources={IMAGE_RESOURCE_KEY: IMAGE_URI},
    )

    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=90, raise_on_error=False
    )

    action = await leader_unit.run_action("resume-upgrade")
    await action.wait()
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=30, status="active"
    )

    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await check_connect_endpoints_status(ops_test, app_name=APP_NAME, port=DEFAULT_API_PORT)
