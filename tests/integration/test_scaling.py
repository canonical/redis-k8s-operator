#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import pytest
from pytest_operator.plugin import OpsTest
from redis import Redis

from .helpers import (
    APP_NAME,
    METADATA,
    NUM_UNITS,
    get_address,
    get_password,
    get_sentinel_password,
    get_unit_map,
    get_unit_number,
    scale,
)

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    resources = {
        "redis-image": METADATA["resources"]["redis-image"]["upstream"],
        "cert-file": METADATA["resources"]["cert-file"]["filename"],
        "key-file": METADATA["resources"]["key-file"]["filename"],
        "ca-cert-file": METADATA["resources"]["ca-cert-file"]["filename"],
    }
    await ops_test.model.deploy(
        charm, resources=resources, application_name=APP_NAME, num_units=NUM_UNITS
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=True,
        timeout=1000,
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


@pytest.mark.run(before="test_scale_down_departing_master")
async def test_scale_up_replication_after_failover(ops_test: OpsTest):
    """Trigger a failover and scale up the application, then test replication status."""
    unit_map = await get_unit_map(ops_test)
    logger.info("Unit mapping: {}".format(unit_map))

    leader_num = get_unit_number(unit_map["leader"])
    leader_address = await get_address(ops_test, unit_num=leader_num)
    password = await get_password(ops_test, leader_num)

    # Set some key on the master replica.
    leader_client = Redis(leader_address, password=password)
    leader_client.set("testKey", "myValue")
    leader_client.close()

    sentinel_password = await get_sentinel_password(ops_test)
    logger.info("retrieved sentinel password for %s: %s", APP_NAME, password)

    # Trigger a master failover
    sentinel = Redis(leader_address, password=sentinel_password, port=26379, decode_responses=True)
    sentinel.execute_command(f"SENTINEL failover {APP_NAME}")
    # Give time so sentinel updates information of failover
    time.sleep(60)

    await ops_test.model.block_until(
        lambda: "failover-status" not in sentinel.execute_command(f"SENTINEL MASTER {APP_NAME}"),
        timeout=60,
    )

    await ops_test.model.applications[APP_NAME].scale(scale=NUM_UNITS + 1)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == NUM_UNITS + 1,
        timeout=300,
    )

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=30,
        raise_on_blocked=True,
        timeout=1000,
    )

    master_info = sentinel.execute_command(f"SENTINEL MASTER {APP_NAME}")
    master_info = dict(zip(master_info[::2], master_info[1::2]))

    # General checks that the system is aware of the new unit
    assert master_info["num-slaves"] == "3"
    assert master_info["quorum"] == "3"
    assert master_info["num-other-sentinels"] == "3"

    unit_map = await get_unit_map(ops_test)
    # Check that the initial key is still replicated across units
    for i in range(NUM_UNITS + 1):
        address = await get_address(ops_test, unit_num=i)
        client = Redis(address, password=password)
        assert client.get("testKey") == b"myValue"
        client.close()


@pytest.mark.run(after="test_scale_up_replication_after_failover")
async def test_scale_down_departing_master(ops_test: OpsTest):
    """Failover to the last unit and scale down."""
    unit_map = await get_unit_map(ops_test)
    logger.info("Unit mapping: {}".format(unit_map))

    # NOTE: since this test will run after the previous, we know that the application
    # has NUM_UNITS + 1 units. Last unit will be application-name/3
    last_unit = NUM_UNITS

    leader_address = await get_address(ops_test, unit_num=get_unit_number(unit_map["leader"]))
    last_address = await get_address(ops_test, unit_num=last_unit)
    password = await get_password(ops_test)
    sentinel_password = await get_sentinel_password(ops_test)

    sentinel = Redis(leader_address, port=26379, password=sentinel_password, decode_responses=True)
    last_redis = Redis(last_address, password=password, decode_responses=True)

    # INITIAL SETUP #
    # Sanity check that the added unit on the previous test is not a master
    assert last_redis.execute_command("ROLE")[0] != "master"

    # Make the added unit a priority during failover
    last_redis.execute_command("CONFIG SET replica-priority 1")
    time.sleep(1)
    # Failover so the last unit becomes master
    sentinel.execute_command(f"SENTINEL FAILOVER {APP_NAME}")
    # Give time so sentinel updates information of failover
    time.sleep(60)

    await ops_test.model.block_until(
        lambda: "failover-status" not in sentinel.execute_command(f"SENTINEL MASTER {APP_NAME}"),
        timeout=60,
    )
    assert last_redis.execute_command("ROLE")[0] == "master"
    last_redis.close()

    # SCALE DOWN #
    await scale(ops_test, scale=NUM_UNITS)

    # Check that the initial key is still replicated across units
    for i in range(NUM_UNITS):
        address = await get_address(ops_test, unit_num=i)
        client = Redis(address, password=password)
        assert client.get("testKey") == b"myValue"
        client.close()

    master_info = sentinel.execute_command(f"SENTINEL MASTER {APP_NAME}")
    master_info = dict(zip(master_info[::2], master_info[1::2]))

    # General checks that the system is reconfigured after departed leader
    assert master_info["num-slaves"] == "2"
    assert master_info["quorum"] == "2"
    assert master_info["num-other-sentinels"] == "2"

    sentinel.close()
