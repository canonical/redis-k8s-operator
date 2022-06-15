#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging

import pytest
from pytest_operator.plugin import OpsTest
from redis import Redis
from redis.exceptions import AuthenticationError

from tests.helpers import APP_NAME, METADATA, NUM_UNITS, TLS_RESOURCES

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


@pytest.mark.password_tests
async def test_database_with_no_password(ops_test: OpsTest):
    """Check that the database cannot be accessed without a password."""
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"]["address"]

    cli = Redis(address)
    # The ping should raise AuthenticationError
    with pytest.raises(AuthenticationError):
        cli.ping()


@pytest.mark.password_tests
async def test_same_password_after_scaling(ops_test: OpsTest):
    """Check that the password remains the same.

    Scale down to 0 and back to 1. Then check that the action returns the same password
    and that it works on the database.
    """
    # Use action to get admin password
    before_pw = await get_password(ops_test)

    logger.info("scaling charm %s to 0 units", APP_NAME)
    await ops_test.model.applications[APP_NAME].scale(scale=0)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 0)

    logger.info("scaling charm %s to 1 units", APP_NAME)
    await ops_test.model.applications[APP_NAME].scale(scale=1)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) > 0)

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=True,
        timeout=1000,
    )

    # Use action to get admin password after scaling
    after_pw = await get_password(ops_test)

    logger.info("before scaling password: %s - after scaling password: %s", before_pw, after_pw)
    assert before_pw == after_pw

    address = await get_address(ops_test)
    cli = Redis(address, password=after_pw)
    assert cli.ping()

    # Reset the number of units to initial state
    logger.info("scaling charm back to %s units", NUM_UNITS)
    await ops_test.model.applications[APP_NAME].scale(scale=NUM_UNITS)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == NUM_UNITS
    )
    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=False,
        timeout=1000,
    )


@pytest.mark.tls_tests
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


@pytest.mark.tls_tests
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
        idle_period=30,
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


@pytest.mark.replication_tests
async def test_replication(ops_test: OpsTest):
    """Check that non leader units are replicas."""
    unit_map = await get_unit_map(ops_test)
    logger.info("Unit mapping: {}".format(unit_map))

    leader_num = get_unit_number(unit_map["leader"])
    leader_address = await get_address(ops_test, leader_num)
    password = await get_password(ops_test, leader_num)

    leader_client = Redis(leader_address, password=password)
    leader_client.set("testKey", "myValue")

    # Check that the initial key has been replicated across units
    for unit_name in unit_map["non_leader"]:
        unit_num = get_unit_number(unit_name)
        address = await get_address(ops_test, unit_num)

        client = Redis(address, password=password)
        assert client.get("testKey") == b"myValue"
        client.close()

    # Reset database satus
    leader_client.delete("testKey")
    leader_client.close()


@pytest.mark.replication_tests
async def test_sentinels_expected(ops_test: OpsTest):
    """Test sentinel connection and expected number of sentinels."""
    # TODO extract number getter to a funct?
    unit_map = await get_unit_map(ops_test)
    leader_num = get_unit_number(unit_map["leader"])
    address = await get_address(ops_test, leader_num)

    sentinel = Redis(address, port=26379)
    sentinels_connected = sentinel.info("sentinel")["master0"]["sentinels"]

    assert sentinels_connected == NUM_UNITS


##################
# Helper methods #
##################


async def get_password(ops_test: OpsTest, num_unit=0) -> str:
    """Use the charm action to retrieve the password.

    Return:
        String with the password stored on the peer relation databag.
    """
    logger.info(f"Calling action to get password for unit {num_unit}")
    action = await ops_test.model.units.get(f"{APP_NAME}/{num_unit}").run_action(
        "get-initial-admin-password"
    )
    password = await action.wait()
    return password.results["redis-password"]


async def attach_resource(ops_test: OpsTest, rsc_name: str, rsc_path: str) -> None:
    """Use the `juju attach-resource` command to add resources."""
    logger.info(f"Attaching resource: attach-resource {APP_NAME} {rsc_name}={rsc_path}")
    await ops_test.juju("attach-resource", APP_NAME, f"{rsc_name}={rsc_path}")


async def change_config(ops_test: OpsTest, values: dict) -> None:
    """Use the `juju config` command to modify a config option."""
    logger.info(f"Changing config options: {values}")
    await ops_test.model.applications[APP_NAME].set_config(values)


async def get_address(ops_test: OpsTest, unit_num=0) -> str:
    """Get the address for a unit."""
    logger.info(f"Getting the address for unit {unit_num}")
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/{unit_num}"]["address"]
    return address


async def get_unit_map(ops_test: OpsTest) -> dict:
    """Get a map of unit names.

    Returns:
        unit_map : {
            "leader": "redis-k8s/0",
            "non_leader": ["redis-k8s/1", "redis-k8s/1"]
        }
    """
    unit_map = {"leader": None, "non_leader": []}
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            # Get the number from the unit
            unit_map["leader"] = unit.name
        else:
            unit_map["non_leader"].append(unit.name)

    return unit_map

def get_unit_number(unit_name: str) -> str:
    """Get the unit number from it's complete name.
    
    Unit names look like `application-name/0`
    """
    return unit_name.split("/")[1]
