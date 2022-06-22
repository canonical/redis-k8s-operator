#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


"""Charm code for sentinel service.

Sentinel provides high availability for Redis.
"""

import logging

from jinja2 import Template
from ops.framework import Object
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

from literals import REDIS_PORT, SENTINEL_CONFIG_PATH, SENTINEL_PORT

logger = logging.getLogger(__name__)


class Sentinel(Object):
    """Sentinel class.

    Deploys sentinel in a separate container, handling the specific events
    related to the Sentinel process.
    """

    def __init__(self, charm) -> None:
        super().__init__(charm, "sentinel")

        self.charm = charm
        self.framework.observe(charm.on.sentinel_pebble_ready, self._sentinel_pebble_ready)

    def _sentinel_pebble_ready(self, event) -> None:
        """Handle pebble ready event for sentinel container."""
        self._update_sentinel_layer()

        # update layer should leave the unit in active status
        if self.charm.unit.status != ActiveStatus():
            event.defer()
            return

    def _update_sentinel_layer(self) -> None:
        """Update the Pebble layer.

        Checks the current container Pebble layer. If the layer is different
        to the new one, Pebble is updated. If not, nothing needs to be done.
        """
        container = self.charm.unit.get_container("sentinel")

        if not container.can_connect():
            self.charm.unit.status = WaitingStatus("Waiting for Pebble in sentinel container")
            return

        if not self.charm._valid_app_databag():
            self.charm.unit.status = WaitingStatus("Databag has not been populated")
            return

        # copy sentinel config file to the container
        self._render_sentinel_config_file()

        # Get current config
        current_layer = container.get_plan()

        # Create the new config layer
        new_layer = self._sentinel_layer()

        # Update the Pebble configuration Layer
        if current_layer.services != new_layer.services:
            logger.debug("About to add_layer with layer_config:\n{}".format(new_layer))
            container.add_layer("sentinel", new_layer, combine=True)
            logger.info("Added updated layer 'sentinel' to Pebble plan")
            container.restart("sentinel")
            logger.info("Restarted sentinel service")

        self.charm.unit.status = ActiveStatus()

    def _sentinel_layer(self) -> Layer:
        """Create the Pebble configuration layer for Redis Sentinel.

        Returns:
            A `ops.pebble.Layer` object with the current layer options
        """
        layer_config = {
            "summary": "Sentinel layer",
            "description": "Sentinel layer",
            "services": {
                "sentinel": {
                    "override": "replace",
                    "summary": "Sentinel service",
                    "command": f"/usr/bin/redis-server {SENTINEL_CONFIG_PATH} --sentinel",
                    "user": "redis",
                    "group": "redis",
                    "startup": "enabled",
                }
            },
        }
        return Layer(layer_config)

    def _render_sentinel_config_file(self) -> None:
        """Render the Sentinel configuration file."""
        # open the template file
        with open("templates/sentinel.conf.j2", "r") as file:
            template = Template(file.read())
        # render the template file with the correct values.
        rendered = template.render(
            hostname=self.charm.unit_pod_hostname,
            master_name=self.charm._name,
            sentinel_port=SENTINEL_PORT,
            redis_master=self.charm.current_master,
            redis_port=REDIS_PORT,
            quorum=1,
            master_password=self.charm._get_password(),
            sentinel_password=self.charm.get_sentinel_password(),
        )
        self._copy_file(SENTINEL_CONFIG_PATH, rendered, "sentinel")

    def _copy_file(self, path: str, rendered: str, container: str) -> None:
        """Copy a string to a path on a container.

        # TODO: Candidate to be extracted to a lib?
        """
        container = self.charm.unit.get_container(container)
        if not container.can_connect():
            logger.warning("Can't connect to {} container".format(container))
            return

        container.push(
            path,
            rendered,
            permissions=0o600,
            user="redis",
            group="redis",
        )
