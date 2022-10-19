#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging

import pytest
from lightkube import AsyncClient
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest
from redis import Redis

from tests.helpers import APP_NAME, METADATA, NUM_UNITS, TLS_RESOURCES
from tests.integration.helpers import (
    attach_resource,
    change_config,
    get_address,
    get_password,
    get_sentinel_password,
    get_unit_map,
    get_unit_number,
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

    # issuing dummy update_status just to trigger an event
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=True,
        timeout=1000,
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

    # effectively disable the update status from firing
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})


@pytest.mark.abort_on_fail
async def test_application_is_up(ops_test: OpsTest):
    """After application deployment, test the database connection.

    Use the action to retrieve the password to connect to the database.
    """
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"]["address"]

    # Use action to get admin password
    password = await get_password(ops_test)
    logger.info("retrieved password for %s: %s", APP_NAME, password)

    cli = Redis(address, password=password)

    assert cli.ping()


async def test_replication(ops_test: OpsTest):
    """Check that non leader units are replicas."""
    unit_map = await get_unit_map(ops_test)
    logger.info("Unit mapping: {}".format(unit_map))

    leader_num = get_unit_number(unit_map["leader"])
    leader_address = await get_address(ops_test, unit_num=leader_num)
    password = await get_password(ops_test, leader_num)

    leader_client = Redis(leader_address, password=password)
    leader_client.set("testKey", "myValue")

    # Check that the initial key has been replicated across units
    for unit_name in unit_map["non_leader"]:
        unit_num = get_unit_number(unit_name)
        address = await get_address(ops_test, unit_num=unit_num)

        client = Redis(address, password=password)
        assert client.get("testKey") == b"myValue"
        client.close()

    # Reset database status
    leader_client.delete("testKey")
    leader_client.close()


async def test_sentinels_expected(ops_test: OpsTest):
    """Test sentinel connection and expected number of sentinels."""
    unit_map = await get_unit_map(ops_test)
    leader_num = get_unit_number(unit_map["leader"])
    address = await get_address(ops_test, unit_num=leader_num)
    # Use action to get admin password
    password = await get_sentinel_password(ops_test)
    logger.info("retrieved sentinel password for %s: %s", APP_NAME, password)

    sentinel = Redis(address, password=password, port=26379)
    sentinels_connected = sentinel.info("sentinel")["master0"]["sentinels"]

    assert sentinels_connected == NUM_UNITS


async def test_delete_non_primary_pod(ops_test: OpsTest):
    """Delete a pod that is not the Redis primary. Check that the deployment is healthy."""
    unit_map = await get_unit_map(ops_test=ops_test)
    non_leader = unit_map["non_leader"][0]
    client = AsyncClient(namespace=ops_test.model_full_name)

    # Delete a non-leader pod
    await client.delete(Pod, name=non_leader.replace("/", "-"))
    logger.info(f"Deleted pod: {non_leader}")

    # Wait for `upgrade_charm` sequence
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=3, idle_period=30
    )

    pod_num = get_unit_number(non_leader)
    pod_address = await get_address(ops_test, unit_num=pod_num)
    password = await get_password(ops_test, pod_num)

    pod_client = Redis(pod_address, password=password, decode_responses=True)
    role = pod_client.role()
    pod_client.close()

    assert ("slave" and "connected") in role


async def test_delete_primary_pod(ops_test: OpsTest):
    """Delete the pod that is the Redis primary. Check that the deployment is healthy."""
    unit_map = await get_unit_map(ops_test=ops_test)
    leader = unit_map["leader"]
    client = AsyncClient(namespace=ops_test.model_full_name)

    # Delete a non-leader pod
    await client.delete(Pod, name=leader.replace("/", "-"))
    logger.info(f"Deleted pod: {leader}")

    # Wait for `upgrade_charm` sequence
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=3, idle_period=30
    )

    # Get unit map again, in the case leader has changed
    unit_map = await get_unit_map(ops_test=ops_test)
    leader = unit_map["leader"]

    pod_num = get_unit_number(leader)
    pod_address = await get_address(ops_test, unit_num=pod_num)
    password = await get_sentinel_password(ops_test, pod_num)

    sentinel = Redis(pod_address, password=password, port=26379)

    assert len(sentinel.sentinel_sentinels(service_name=APP_NAME)) == NUM_UNITS
    assert len(sentinel.sentinel_slaves()) == NUM_UNITS - 1


@pytest.mark.skip  # TLS will not be implemented as resources in the future
async def test_blocked_if_no_certificates(ops_test: OpsTest):
    """Check the application status on TLS enable.

    Will enable TLS without providing certificates. This should result
    on a Blocked status.
    """
    await change_config(ops_test, {"enable-tls": "true"})

    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=1000)

    logger.info("trying to check for blocked status")
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

    # Reset application status
    await change_config(ops_test, {"enable-tls": "false"})
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)


@pytest.mark.skip  # TLS will not be implemented as resources in the future
async def test_enable_tls(ops_test: OpsTest):
    """Check adding TLS certificates and enabling them.

    After adding the resources and enabling TLS, waits until the
    application is on a Active status. Then, ping the database.
    """
    # each resource contains ("rsc_name", "rsc_path")
    for rsc_name, src_path in TLS_RESOURCES.items():
        await attach_resource(ops_test, rsc_name, src_path)

    # FIXME: A wait here is not guaranteed to work. It can succeed before resources
    # have been added. Additionally, attaching resources can result on transient error
    # states for the application while is stabilizing again.
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=60,
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=1000,
    )

    await change_config(ops_test, {"enable-tls": "true"})
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=1000
    )

    password = await get_password(ops_test)
    address = await get_address(ops_test)

    # connect using the ca certificate
    client = Redis(
        address, password=password, ssl=True, ssl_ca_certs=TLS_RESOURCES["ca-cert-file"]
    )
    assert client.ping()
    client.close()

    await change_config(ops_test, {"enable-tls": "false"})
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=1000
    )

    client = Redis(address, password=password, ssl=False)
    assert client.ping()
    client.close()
