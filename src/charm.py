#!/usr/bin/env python3
# This file is part of the Redis k8s Charm for Juju.
# Copyright 2021 Canonical Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3, as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""Charm code for Redis service."""

import logging
from typing import Optional

from charms.redis_k8s.v0.redis import RedisProvides
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus, Relation
from ops.pebble import Layer, ConnectionError
from redis import Redis
from redis.exceptions import RedisError

REDIS_PORT = 6379
WAITING_MESSAGE = "Waiting for Redis..."
PEER = "redis-peers"

logger = logging.getLogger(__name__)


class RedisK8sCharm(CharmBase):
    """Charm the service.

    Deploy a standalone instance of redis-server, using Pebble as an entry
    point to the service.
    """

    def __init__(self, *args):
        super().__init__(*args)

        self.redis_provides = RedisProvides(self, port=REDIS_PORT)

        self.framework.observe(self.on.redis_pebble_ready, self._redis_pebble_ready)
        self.framework.observe(self.on.config_changed, self._config_changed)
        self.framework.observe(self.on.upgrade_charm, self._config_changed)
        self.framework.observe(self.on.update_status, self._update_status)

        self.framework.observe(self.on.check_service_action, self.check_service)

    def _redis_pebble_ready(self, _) -> None:
        """Handle the pebble_ready event.

        Updates the Pebble layer if needed.
        """
        self._update_layer()

    def _config_changed(self, event) -> None:
        """Handle config_changed event.

        Updates the Pebble layer if needed. Finally, checks the redis service
        updating the unit status with the result.
        """
        self._update_layer()

        # update_layer will set a Waiting status if Pebble is not ready
        if self.unit.status != ActiveStatus():
            event.defer()
            return

        self._redis_check()

    def _update_status(self, event):
        """Handle update_status event.

        On update status, check the container.
        """
        logger.info("Beginning update_status")
        self._redis_check()

    def _update_layer(self) -> None:
        """Update the Pebble layer.

        Checks the current container Pebble layer. If the layer is different
        to the new one, Pebble is updated. If not, nothing needs to be done.
        """
        container = self.unit.get_container("redis")
        
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble in workload container")
            return

        # Get current config
        current_layer = container.get_plan()

        # Create the new config layer
        new_layer = self._redis_layer()

        # Update the Pebble configuration Layer
        if current_layer.services != new_layer.services:
            logger.debug("About to add_layer with layer_config:\n{}".format(new_layer))
            container.add_layer("redis", new_layer, combine=True)
            logger.info("Added updated layer 'redis' to Pebble plan")
            container.restart("redis")
            logger.info("Restarted redis service")

        self.unit.status = ActiveStatus()

    def _redis_layer(self) -> Layer:
        """Create the Pebble configuration layer for Redis.
        
        Returns:
            A `ops.pebble.Layer` object with the current layer options
        """
        layer_config = {
            "summary": "Redis layer",
            "description": "Redis layer",
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": "/usr/local/bin/start-redis.sh redis-server",
                    "startup": "enabled",
                    "environment": {"ALLOW_EMPTY_PASSWORD": "yes"},
                }
            },
        }
        return Layer(layer_config)

    def _redis_check(self):
        """Checks is the Redis database is active."""
        try:
            redis = Redis()
            info = redis.info("server")
            version = info["redis_version"]
            self.unit.status = ActiveStatus()
            self.unit.set_workload_version(version)
            if self.unit.is_leader():
                self.app.status = ActiveStatus()
            return True
        except RedisError:
            self.unit.status = WaitingStatus(WAITING_MESSAGE)
            if self.unit.is_leader():
                self.app.status = WaitingStatus(WAITING_MESSAGE)
            return False

    def check_service(self, event):
        """Handle for check_service action.

        Checks if redis-server is active and running, setting the unit
        status with the result.
        """
        logger.info("Beginning check_service")
        results = {}
        if self._redis_check():
            results["result"] = "Service is running"
        else:
            results["result"] = "Service is not running"
        event.set_results(results)

    @property
    def _peers(self) -> Optional[Relation]:
        """Fetch the peer relation.

        Returns:
            An `ops.model.Relation` object representing the peer relation.
        """
        return self.model.get_relation(PEER)


if __name__ == "__main__":  # pragma: nocover
    main(RedisK8sCharm)
