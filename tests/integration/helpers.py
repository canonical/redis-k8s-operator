#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for integration tests."""
import logging
import subprocess
from urllib.request import urlopen

from pytest_operator.plugin import OpsTest
from tenacity import before_log, retry, stop_after_attempt, wait_fixed

from tests.helpers import APP_NAME

logger = logging.getLogger(__name__)


async def scale(ops_test: OpsTest, scale: int) -> None:
    """Scale the application to the provided number and wait for idle."""
    await ops_test.model.applications[APP_NAME].scale(scale=scale)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == scale
    )

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=30,
        raise_on_blocked=True,
        timeout=1000,
    )


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


async def get_sentinel_password(ops_test: OpsTest, num_unit=0) -> str:
    """Use the charm action to retrieve the sentinel password.

    Return:
        String with the password stored on the peer relation databag.
    """
    logger.info(f"Calling action to get sentinel password for unit {num_unit}")
    action = await ops_test.model.units.get(f"{APP_NAME}/{num_unit}").run_action(
        "get-sentinel-password"
    )
    password = await action.wait()
    return password.results["sentinel-password"]


async def attach_resource(ops_test: OpsTest, rsc_name: str, rsc_path: str) -> None:
    """Use the `juju attach-resource` command to add resources."""
    logger.info(f"Attaching resource: attach-resource {APP_NAME} {rsc_name}={rsc_path}")
    await ops_test.juju("attach-resource", APP_NAME, f"{rsc_name}={rsc_path}")


async def change_config(ops_test: OpsTest, values: dict) -> None:
    """Use the `juju config` command to modify a config option."""
    logger.info(f"Changing config options: {values}")
    await ops_test.model.applications[APP_NAME].set_config(values)


async def get_address(ops_test: OpsTest, app_name=APP_NAME, unit_num=0) -> str:
    """Get the address for a unit."""
    logger.info(f"Getting the address for unit {unit_num}")
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]
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


def check_application_status(ops_test: OpsTest, app_name: str) -> str:
    """Return the application status for an app name."""
    model_name = ops_test.model.info.name
    proc = subprocess.check_output(f"juju status --model={model_name}".split())
    proc = proc.decode("utf-8")

    statuses = {"active", "maintenance", "waiting", "blocked"}
    for line in proc.splitlines():
        parts = line.split()
        # first line with app name will have application status
        if parts and parts[0] == app_name:
            # NOTE: intersects possible statuses with the list of values:
            # this is done because sometimes version number exists and
            # sometimes it doesn't on juju status output
            find_status = list(statuses & set(parts))
            if find_status:
                return find_status[0]


def get_unit_number(unit_name: str) -> str:
    """Get the unit number from it's complete name.

    Unit names look like `application-name/0`
    """
    return unit_name.split("/")[1]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    reraise=True,
    before=before_log(logger, logging.DEBUG),
)
def query_url(url: str):
    """Connect to a url and return the result."""
    logger.info("Trying to connect to: {}".format(url))
    response = urlopen(url)

    return response
