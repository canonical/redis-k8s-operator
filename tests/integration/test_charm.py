#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from redis import Redis
from redis.exceptions import AuthenticationError

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    resources = {"redis-image": METADATA["resources"]["redis-image"]["upstream"]}
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME)

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
    logger.info("calling action to retrieve password")
    password = await get_password(ops_test)

    cli = Redis(address, password=password)

    assert cli.ping()


@pytest.mark.abort_on_fail
async def test_database_with_no_password(ops_test: OpsTest):
    """Check that the database cannot be accessed without a password."""
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"]["address"]

    cli = Redis(address)
    # The ping should raise AuthenticationError
    with pytest.raises(AuthenticationError):
        cli.ping()


@pytest.mark.abort_on_fail
async def test_same_password_after_scaling(ops_test: OpsTest):
    """Check that the password remains the same.

    Scale down to 0 and back to 1. Then check that the action returns the same password
    and that it works on the database.
    """
    # Use action to get admin password
    logger.info("calling action to retrieve password")
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
    logger.info("calling action to retrieve password")
    after_pw = await get_password(ops_test)

    assert before_pw == after_pw

    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"]["address"]
    cli = Redis(address, password=after_pw)
    assert cli.ping()


##################
# Helper methods #
##################


async def get_password(ops_test: OpsTest) -> str:
    """Use the charm action to retrieve the password.

    Return:
        String with the password stored on the peer relation databag.
    """
    action = await ops_test.model.units.get(f"{APP_NAME}/0").run_action(
        "get-initial-admin-password"
    )
    password = await action.wait()
    return password.results["redis-password"]
