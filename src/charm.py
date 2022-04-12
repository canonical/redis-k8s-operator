#!/usr/bin/env python3
# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.
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
import secrets
import shutil
import string
from typing import List, Optional

from charms.redis_k8s.v0.redis import RedisProvides
from ops.charm import ActionEvent, CharmBase
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, ModelError, Relation, WaitingStatus
from ops.pebble import Layer
from redis.exceptions import RedisError

from redis_client import redis_client

REDIS_PORT = 6379
WAITING_MESSAGE = "Waiting for Redis..."
CONFIG_PATH = "/etc/redis/"
PEER = "redis-peers"
PEER_PASSWORD_KEY = "redis-password"


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
        self.framework.observe(self.on.leader_elected, self._leader_elected)
        self.framework.observe(self.on.config_changed, self._config_changed)
        self.framework.observe(self.on.upgrade_charm, self._upgrade_charm)
        self.framework.observe(self.on.update_status, self._update_status)

        self.framework.observe(self.on.check_service_action, self.check_service)
        self.framework.observe(
            self.on.get_initial_admin_password_action, self._get_password_action
        )

        self._storage_path = self.meta.storages["database"].location

    def _redis_pebble_ready(self, _) -> None:
        """Handle the pebble_ready event.

        Updates the Pebble layer if needed.
        """
        self._update_layer()

    def _upgrade_charm(self, _) -> None:
        """Handle the upgrade_charm event.

        Tries to store the certificates on the redis container, as new `juju attach-resource`
        will trigger this event.
        """
        if not self._store_certificates():
            # NOTE: when updating certificates (a rotation for example), which implies
            # that there are already some files stored on the resources, this will not
            # trigger, but the certificates will not be valid as a whole.
            self.unit.status = WaitingStatus("Not all certificates have been provided")

    def _leader_elected(self, _) -> None:
        """Handle the leader_elected event.

        If no password exists, a new one will be created for accessing Redis. This password
        will be stored on the peer relation databag.
        """
        redis_password = self._get_password()

        if not redis_password:
            self._peers.data[self.app][PEER_PASSWORD_KEY] = self._generate_password()

    def _config_changed(self, event: EventBase) -> None:
        """Handle config_changed event.

        Updates the Pebble layer if needed. Finally, checks the redis service
        updating the unit status with the result.
        """
        # Check that certificates for TLS exist
        if self.config["enable-tls"] and self._retrieve_certificates() is None:
            logger.warning("Not enough certificates found for TLS")
            self.unit.status = BlockedStatus("No certificates found")
            return

        self._update_layer()

        # update_layer will set a Waiting status if Pebble is not ready
        if self.unit.status != ActiveStatus():
            event.defer()
            return

        self._redis_check()

    def _update_status(self, _) -> None:
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
                    "environment": {
                        "REDIS_PASSWORD": self._get_password(),
                        "REDIS_EXTRA_FLAGS": self._redis_extra_flags(),
                    },
                }
            },
        }
        return Layer(layer_config)

    def _redis_extra_flags(self) -> str:
        """Generate the REDIS_EXTRA_FLAGS environment variable for the container.

        Will check config options to decide the extra commands passed at the
        redis-server service. Currently only TLS is an option.
        """
        extra_flags = []
        if self.config["enable-tls"]:
            extra_flags += [
                f"--tls-port {REDIS_PORT}",
                "--port 0",
                "--tls-auth-clients optional",
                f"--tls-cert-file {self._storage_path}/redis.crt",
                f"--tls-key-file {self._storage_path}/redis.key",
                f"--tls-ca-cert-file {self._storage_path}/ca.crt",
            ]
        return " ".join(extra_flags)

    def _redis_check(self) -> None:
        """Checks is the Redis database is active."""
        try:
            redis = redis_client(
                self._get_password(), self.config["enable-tls"], self._storage_path
            )
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

    def _get_password_action(self, event: ActionEvent) -> None:
        """Handle the get_initial_admin_password event.

        Sets the result of the action with the admin password for Redis.
        """
        event.set_results({"redis-password": self._get_password()})

    @property
    def _peers(self) -> Optional[Relation]:
        """Fetch the peer relation.

        Returns:
            An `ops.model.Relation` object representing the peer relation.
        """
        return self.model.get_relation(PEER)

    def _generate_password(self) -> str:
        """Generate a random 16 character password string.

        Returns:
           A random password string.
        """
        choices = string.ascii_letters + string.digits
        password = "".join([secrets.choice(choices) for i in range(16)])
        return password

    def _get_password(self) -> str:
        """Get the current admin password for Redis.

        Returns:
            String with the password
        """
        data = self._peers.data[self.app]
        return data.get(PEER_PASSWORD_KEY, "")

    def _store_certificates(self) -> bool:
        """Copy the TLS certificates to the redis container.

        Returns:
            True if the certificates can be copied, false otherwise.
        """
        cert_paths = self._retrieve_certificates()

        if cert_paths is None:
            return False

        # Copy the files from the resources location to the redis container.
        for cert_path in cert_paths:
            shutil.copy(cert_path, self._storage_path)

        return True

    def _retrieve_certificates(self) -> Optional[List]:
        """Check that TLS certificates exist and return them.

        Returns:
            List with the paths of the certificates or None
        """
        try:
            resources = ["cert-file", "key-file", "ca-cert-file"]
            # Fetch the resource path
            resource_paths = [self.model.resources.fetch(resource) for resource in resources]
            return resource_paths
        except ModelError as e:
            self.unit.status = BlockedStatus(
                "Something went wrong when claiming resource; run `juju debug-log` for more info'"
            )
            # might actually be worth it to just reraise this exception and let the
            # charm error out; depends on whether we can recover from this.
            logger.error(e)
            return None
        except NameError as e:
            self.unit.status = BlockedStatus(
                "Resource not found; did you forget to declare it in metadata.yaml?"
            )
            logger.error(e)
            return None


if __name__ == "__main__":  # pragma: nocover
    main(RedisK8sCharm)
