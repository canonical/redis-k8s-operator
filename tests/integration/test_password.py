#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest
from redis import Redis
from redis.exceptions import AuthenticationError

from .helpers import APP_NAME, METADATA, get_address, get_password

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
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, num_units=1)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=True,
        timeout=1000,
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


async def test_database_with_no_password(ops_test: OpsTest):
    """Check that the database cannot be accessed without a password."""
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"]["address"]

    cli = Redis(address)
    # The ping should raise AuthenticationError
    with pytest.raises(AuthenticationError):
        cli.ping()


async def test_same_password_after_scaling(ops_test: OpsTest):
    """Check that the password remains the same.

    Scale down to 0 and back to 1. Then check that the action returns the same password
    and that it works on the database.
    """
    # Use action to get admin password
    before_pw = await get_password(ops_test)

    logger.info("scaling charm %s to 0 units", APP_NAME)
    await ops_test.model.applications[APP_NAME].scale(scale=0)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == 0, timeout=600
    )

    logger.info("scaling charm %s to 1 units", APP_NAME)
    await ops_test.model.applications[APP_NAME].scale(scale=1)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) > 0, timeout=600
    )

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
