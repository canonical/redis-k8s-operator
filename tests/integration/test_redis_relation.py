#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest as pytest
from lightkube import AsyncClient
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

from tests.helpers import APP_NAME, METADATA
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


@pytest.fixture(scope="module", name="num_units")
def num_units_fixture(request):
    return request.config.getoption("--num-units")


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, num_units: int):
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
                num_units=num_units,
                series="focal",
            ),
            ops_test.model.deploy(
                FIRST_DISCOURSE_APP_NAME, application_name=FIRST_DISCOURSE_APP_NAME, series="focal"
            ),
            ops_test.model.deploy(
                POSTGRESQL_APP_NAME,
                application_name=POSTGRESQL_APP_NAME,
                channel="14/stable",
                series="jammy",
            ),
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, POSTGRESQL_APP_NAME], status="active", idle_period=20, timeout=3000
        )
        # Discourse becomes blocked waiting for relations.
        await ops_test.model.wait_for_idle(
            apps=[FIRST_DISCOURSE_APP_NAME], status="waiting", idle_period=20, timeout=3000
        )

    assert (
        ops_test.model.applications[FIRST_DISCOURSE_APP_NAME].units[0].workload_status == "waiting"
    )
    assert ops_test.model.applications[POSTGRESQL_APP_NAME].units[0].workload_status == "active"


@pytest.mark.skip_if_deployed
async def test_discourse_relation(ops_test: OpsTest):
    # Test the first Discourse charm.
    # Add both relations to Discourse (PostgreSQL and Redis)
    # and wait for it to be ready.
    await ops_test.model.relate(f"{POSTGRESQL_APP_NAME}:database", FIRST_DISCOURSE_APP_NAME)
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
        lambda: check_application_status(ops_test, FIRST_DISCOURSE_APP_NAME) == "active",
        timeout=900,
        wait_period=5,
    )
    await ops_test.model.block_until(
        lambda: check_application_status(ops_test, POSTGRESQL_APP_NAME) == "active",
        timeout=900,
        wait_period=5,
    )


async def test_discourse_request(ops_test: OpsTest):
    """Try to connect to discourse after the bundle is deployed."""
    discourse_ip = await get_address(ops_test, app_name=FIRST_DISCOURSE_APP_NAME)
    url = f"http://{discourse_ip}:3000/site.json"
    response = query_url(url)

    assert response.status == 200


async def test_delete_redis_pod(ops_test: OpsTest):
    """Delete the leader redis-k8s pod.

    Check relation data updated with the new redis-k8s pod IP after pod revived by juju.
    """
    unit_map = await get_unit_map(ops_test=ops_test)
    leader = unit_map["leader"]
    leader_unit_num = int(leader.split("/")[-1])
    redis_ip_before = await get_address(ops_test, app_name=APP_NAME, unit_num=leader_unit_num)

    client = AsyncClient(namespace=ops_test.model.info.name)
    await client.delete(Pod, name=f"{APP_NAME}-{leader_unit_num}")
    # Wait for `upgrade_charm` sequence
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=60
    )
    await ops_test.model.block_until(
        lambda: check_application_status(ops_test, FIRST_DISCOURSE_APP_NAME) == "active",
        timeout=600,
        wait_period=5,
    )

    redis_ip_after = await get_address(ops_test, app_name=APP_NAME, unit_num=leader_unit_num)
    discourse_ip = await get_address(ops_test, app_name=FIRST_DISCOURSE_APP_NAME)
    url = f"http://{discourse_ip}:3000/site.json"
    response = query_url(url)

    assert redis_ip_before != redis_ip_after
    assert response.status == 200
