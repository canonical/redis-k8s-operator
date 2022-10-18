#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest as pytest
from pytest_operator.plugin import OpsTest

from tests.helpers import APP_NAME, METADATA, NUM_UNITS
from tests.integration.helpers import (
    check_application_status,
    get_address,
    get_unit_map,
    get_unit_number,
    query_url,
)

FIRST_DISCOURSE_APP_NAME = "discourse-k8s"
SECOND_DISCOURSE_APP_NAME = "discourse-charmers-discourse-k8s"
POSTGRESQL_APP_NAME = "postgresql-k8s"

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it.

    Assert on the unit status before any relations/configurations take place.
    """
    async with ops_test.fast_forward():
        # Build and deploy charm from local source folder (and also postgresql from Charmhub)
        # Both are needed by Discourse charms.
        charm = await ops_test.build_charm(".")
        resources = {
            "redis-image": METADATA["resources"]["redis-image"]["upstream"],
            "cert-file": METADATA["resources"]["cert-file"]["filename"],
            "key-file": METADATA["resources"]["key-file"]["filename"],
            "ca-cert-file": METADATA["resources"]["ca-cert-file"]["filename"],
        }
        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                resources=resources,
                application_name=APP_NAME,
                trust=True,
                num_units=NUM_UNITS,
            ),
            ops_test.model.deploy(
                FIRST_DISCOURSE_APP_NAME, application_name=FIRST_DISCOURSE_APP_NAME
            ),
            ops_test.model.deploy(POSTGRESQL_APP_NAME, application_name=POSTGRESQL_APP_NAME),
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, POSTGRESQL_APP_NAME], status="active", timeout=3000
        )
        # Discourse becomes blocked waiting for relations.
        await ops_test.model.wait_for_idle(
            apps=[FIRST_DISCOURSE_APP_NAME], status="blocked", timeout=3000
        )

    assert (
        ops_test.model.applications[FIRST_DISCOURSE_APP_NAME].units[0].workload_status == "blocked"
    )
    assert ops_test.model.applications[POSTGRESQL_APP_NAME].units[0].workload_status == "active"


@pytest.mark.skip_if_deployed
async def test_discourse_relation(ops_test: OpsTest):
    # Test the first Discourse charm.
    # Add both relations to Discourse (PostgreSQL and Redis)
    # and wait for it to be ready.
    await ops_test.model.relate(f"{POSTGRESQL_APP_NAME}:db-admin", FIRST_DISCOURSE_APP_NAME)
    # Wait until discourse handles all relation events related to postgresql
    await ops_test.model.relate(APP_NAME, FIRST_DISCOURSE_APP_NAME)

    # This won't work: model.applications[app_name].units[0].workload_status returns wrong status
    """
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, FIRST_DISCOURSE_APP_NAME, POSTGRESQL_APP_NAME],
        status="active",
        idle_period=30,
        timeout=3000,  # Discourse takes a longer time to become active (a lot of setup).
    )
    """

    await ops_test.model.block_until(
        lambda: check_application_status(ops_test, "discourse-k8s") == "active",
        timeout=600,
        wait_period=5,
    )


async def test_discourse_request(ops_test: OpsTest):
    """Try to connect to discourse after the bundle is deployed."""
    discourse_ip = await get_address(ops_test, app_name=FIRST_DISCOURSE_APP_NAME)
    url = f"http://{discourse_ip}:3000/site.json"
    response = query_url(url)

    assert response.status == 200


async def test_discourse_from_discourse_charmers(ops_test: OpsTest):
    """Test the second Discourse charm."""
    unit_map = await get_unit_map(ops_test)

    # Get the Redis instance IP address.
    redis_host = await get_address(ops_test, unit_num=get_unit_number(unit_map["leader"]))

    # Deploy Discourse and wait for it to be blocked waiting for database relation.
    await ops_test.model.deploy(
        SECOND_DISCOURSE_APP_NAME,
        application_name=SECOND_DISCOURSE_APP_NAME,
        config={
            "redis_host": redis_host,
            "developer_emails": "user@foo.internal",
            "external_hostname": "foo.internal",
            "smtp_address": "127.0.0.1",
            "smtp_domain": "foo.internal",
        },
    )
    # Discourse becomes blocked waiting for PostgreSQL relation.
    await ops_test.model.wait_for_idle(
        apps=[SECOND_DISCOURSE_APP_NAME], status="blocked", timeout=3000
    )

    # Relate PostgreSQL and Discourse, waiting for Discourse to be ready.
    await ops_test.model.add_relation(
        f"{POSTGRESQL_APP_NAME}:db-admin",
        SECOND_DISCOURSE_APP_NAME,
    )
    await ops_test.model.wait_for_idle(
        apps=[POSTGRESQL_APP_NAME, SECOND_DISCOURSE_APP_NAME, APP_NAME],
        status="active",
        timeout=3000,  # Discourse takes a longer time to become active (a lot of setup).
    )
