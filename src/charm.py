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

from contextlib import contextmanager
from email import contentmanager
import logging
import secrets
import socket
import string
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from charms.redis_k8s.v0.redis import RedisProvides
from ops.charm import ActionEvent, CharmBase
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, ModelError, Relation, WaitingStatus
from ops.pebble import Layer
from redis import Redis
from redis.exceptions import RedisError

from literals import (
    LEADER_HOST_KEY,
    PEER,
    PEER_PASSWORD_KEY,
    REDIS_PORT,
    WAITING_MESSAGE,
)

logger = logging.getLogger(__name__)


class RedisK8sCharm(CharmBase):
    """Charm the service.

    Deploy a standalone instance of redis-server, using Pebble as an entry
    point to the service.
    """

    def __init__(self, *args):
        super().__init__(*args)

        self._unit_name = self.unit.name
        self._name = self.model.app.name
        self._namespace = self.model.name
        self.redis_provides = RedisProvides(self, port=REDIS_PORT)

        self.framework.observe(self.on.redis_pebble_ready, self._redis_pebble_ready)
        self.framework.observe(self.on.leader_elected, self._leader_elected)
        self.framework.observe(self.on.config_changed, self._config_changed)
        self.framework.observe(self.on.upgrade_charm, self._upgrade_charm)
        self.framework.observe(self.on.update_status, self._update_status)

        self.framework.observe(self.on.redis_relation_created, self._on_redis_relation_created)
        self.framework.observe(self.on.redis_peers_relation_changed, self._peer_relation_handler)

        self.framework.observe(self.on.check_service_action, self.check_service)
        self.framework.observe(
            self.on.get_initial_admin_password_action, self._get_password_action
        )

        self._storage_path = self.meta.storages["database"].location

    def _redis_pebble_ready(self, _) -> None:
        """Handle the pebble_ready event.

        Updates the Pebble layer if needed.
        """
        self._store_certificates()
        self._update_layer()

    def _upgrade_charm(self, _) -> None:
        """Handle the upgrade_charm event.

        Tries to store the certificates on the redis container, as new `juju attach-resource`
        will trigger this event.
        """
        self._store_certificates()

    def _leader_elected(self, _) -> None:
        """Handle the leader_elected event.

        If no password exists, a new one will be created for accessing Redis. This password
        will be stored on the peer relation databag.
        """
        if self._current_master is None:
            leader_hostname = self._get_pod_hostname()
            logger.info("Initial replication, setting leader-host to {}".format(leader_hostname))
            self._peers.data[self.app][LEADER_HOST_KEY] = leader_hostname

        if not self._get_password():
            logger.info("Creating password for application")
            self._peers.data[self.app][PEER_PASSWORD_KEY] = self._generate_password()

    def _config_changed(self, event: EventBase) -> None:
        """Handle config_changed event.

        Updates the Pebble layer if needed. Finally, checks the redis service
        updating the unit status with the result.
        """
        # Check that certificates exist if TLS is enabled
        if self.config["enable-tls"] and None in self._certificates:
            logger.warning("Not enough certificates found for TLS")
            self.unit.status = BlockedStatus("Not enough certificates found")
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

    def _peer_relation_handler(self, event):
        """Handle relation for joining units."""
        self._update_layer()

        # update layer should leave the unit in active status
        if self.unit.status != ActiveStatus():
            event.defer()
            return

    def _on_redis_relation_created(self, _):
        """Handle the relation created event."""
        # TODO: Update warning to point to the new interface once it is created
        logger.warning("DEPRECATION WARNING - `redis` interface is a legacy interface.")
        if self.unit.is_leader():
            self._peers.data[self.app]["enable-password"] = "false"
            self._update_layer()

    def _update_layer(self) -> None:
        """Update the Pebble layer.

        Checks the current container Pebble layer. If the layer is different
        to the new one, Pebble is updated. If not, nothing needs to be done.
        """
        container = self.unit.get_container("redis")

        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble in workload container")
            return

        if not self._valid_app_databag():
            self.unit.status = WaitingStatus("Waiting for peer data to be updated")
            return

        # Get current config
        current_layer = container.get_plan()

        # Create the new config layer
        new_layer = self._redis_layer()

        # NOTE: This block is to allow the legacy `redis` relation interface to work
        # with charms still using it. Charms using the relation don't expect Redis to
        # have a password.
        if self._peers.data[self.app].get("enable-password", "true") == "false":
            logger.warning(
                "DEPRECATION WARNING - password off, this will be removed on later versions"
            )
            env = new_layer.services["redis"].environment
            env["ALLOW_EMPTY_PASSWORD"] = "yes"
            if "REDIS_PASSWORD" in env:
                del env["REDIS_PASSWORD"]

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
        redis-server service.
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

        # Non leader units will be replicas of the leader unit
        if not self.unit.is_leader():
            extra_flags += [f"--replicaof {self._current_master} {REDIS_PORT}"]

            if self.config["enable-tls"]:
                extra_flags += ["--tls-replication yes"]

            # NOTE: (DEPRECATE) This check will evaluate to false in the case the `redis`
            # relation interface is being used.
            if self._peers.data[self.app].get("enable-password", "true") == "true":
                extra_flags += [f"--masterauth {self._get_password()}"]

        logger.debug("Extra flags: {}".format(extra_flags))

        return " ".join(extra_flags)

    def _redis_check(self) -> None:
        """Checks if the Redis database is active."""
        try:
            with self._redis_client() as redis:
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

    @property
    def _certificates(self) -> List[Optional[Path]]:
        """Paths of the certificate files.

        Returns:
            A list with the paths of the certificates or None where no path can be found
        """
        resources = ["cert-file", "key-file", "ca-cert-file"]
        return [self._retrieve_resource(res) for res in resources]

    @property
    def _current_master(self) -> Optional[str]:
        """Get the current master."""
        return self._peers.data[self.app].get(LEADER_HOST_KEY)

    def _valid_app_databag(self) -> bool:
        """Check if the peer databag has been populated.

        Returns:
            bool: True if the databag has been populated, false otherwise
        """
        password = self._get_password()

        # NOTE: (DEPRECATE) Only used for the redis legacy relation. The password
        # is not relevant when that relation is used
        if self._peers.data[self.app].get("enable-password", "true") == "false":
            password = True

        return bool(password and self._current_master)

    def _generate_password(self) -> str:
        """Generate a random 16 character password string.

        Returns:
           A random password string.
        """
        choices = string.ascii_letters + string.digits
        password = "".join([secrets.choice(choices) for i in range(16)])
        return password

    def _get_password(self) -> Optional[str]:
        """Get the current admin password for Redis.

        Returns:
            String with the password
        """
        data = self._peers.data[self.app]
        # NOTE: (DEPRECATE) When using redis legacy relation, no password is used
        if data.get("enable-password", "true") == "false":
            return None

        return data.get(PEER_PASSWORD_KEY)

    def _store_certificates(self) -> None:
        """Copy the TLS certificates to the redis container."""
        # Get a list of valid paths
        cert_paths = list(filter(None, self._certificates))
        container = self.unit.get_container("redis")

        # Copy the files from the resources location to the redis container.
        # TODO handle error case
        for cert_path in cert_paths:
            with open(cert_path, "r") as f:
                container.push((f"{self._storage_path}/{cert_path.name}"), f)

    def _retrieve_resource(self, resource: str) -> Optional[Path]:
        """Check that the resource exists and return it.

        Returns:
            Path of the resource or None
        """
        try:
            # Fetch the resource path
            return self.model.resources.fetch(resource)
        except (ModelError, NameError) as e:
            logger.warning(e)
            return None

    def _get_pod_hostname(self, name="") -> str:
        """Creates the pod hostname from its name."""
        return socket.getfqdn(name)

    @contextmanager
    def _redis_client(self, hostname="localhost") -> Redis:
        """Creates a Redis client on a given hostname.

        All parameters are passed, will default to the same values under `Redis` constructor

        Returns:
            Redis: redis client
        """
        ca_cert_path = self._retrieve_resource("ca-cert-file")
        client = Redis(
            host=hostname,
            port=REDIS_PORT,
            password=self._get_password(),
            ssl=self.config["enable-tls"],
            ssl_ca_certs=ca_cert_path,
        )
        try:
            yield client
        finally:
            client.close()


if __name__ == "__main__":  # pragma: nocover
    main(RedisK8sCharm)
