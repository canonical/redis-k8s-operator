#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm code for Redis service."""

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
from redis import ConnectionError, Redis, TimeoutError
from redis.exceptions import RedisError
from tenacity import before_log, retry, stop_after_attempt, wait_fixed

from literals import (
    LEADER_HOST_KEY,
    PEER,
    PEER_PASSWORD_KEY,
    REDIS_PORT,
    SENTINEL_PASSWORD_KEY,
    SOCKET_TIMEOUT,
    WAITING_MESSAGE,
)
from sentinel import Sentinel

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
        self.sentinel = Sentinel(self)

        self.framework.observe(self.on.redis_pebble_ready, self._redis_pebble_ready)
        self.framework.observe(self.on.leader_elected, self._leader_elected)
        self.framework.observe(self.on.config_changed, self._config_changed)
        self.framework.observe(self.on.upgrade_charm, self._upgrade_charm)
        self.framework.observe(self.on.update_status, self._update_status)

        self.framework.observe(self.on.redis_relation_created, self._on_redis_relation_created)
        self.framework.observe(self.on[PEER].relation_changed, self._peer_relation_changed)
        self.framework.observe(self.on[PEER].relation_departed, self._peer_relation_departed)

        self.framework.observe(self.on.check_service_action, self.check_service)
        self.framework.observe(
            self.on.get_initial_admin_password_action, self._get_password_action
        )
        self.framework.observe(
            self.on.get_sentinel_password_action, self._get_sentinel_password_action
        )

        self._storage_path = self.meta.storages["database"].location

    def _redis_pebble_ready(self, event) -> None:
        """Handle the pebble_ready event.

        Updates the Pebble layer if needed.
        """
        self._store_certificates()
        self._update_layer()

        # update_layer will set a Waiting status if Pebble is not ready
        if not isinstance(self.unit.status, ActiveStatus):
            event.defer()
            return

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
        if self.current_master is None:
            logger.info(
                "Initial replication, setting leader-host to {}".format(self.unit_pod_hostname)
            )
            self._peers.data[self.app][LEADER_HOST_KEY] = self.unit_pod_hostname
        else:
            # TODO extract to method shared with relation_departed
            self._update_application_master()
            self._update_quorum()
            try:
                self._is_failover_finished()
            except Exception:
                raise

            logger.warning("Resetting sentinel")
            self._reset_sentinel()

        if not self._get_password():
            logger.info("Creating password for application")
            self._peers.data[self.app][PEER_PASSWORD_KEY] = self._generate_password()

        if not self.get_sentinel_password():
            logger.info("Creating sentinel password")
            self._peers.data[self.app][SENTINEL_PASSWORD_KEY] = self._generate_password()

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
        if not isinstance(self.unit.status, ActiveStatus):
            event.defer()
            return

        self._redis_check()

    def _update_status(self, _) -> None:
        """Handle update_status event.

        On update status, check the container.
        """
        logger.info("Beginning update_status")
        if self.unit.is_leader():
            self._update_application_master()
        self._redis_check()

    def _peer_relation_changed(self, event):
        """Handle relation for joining units."""
        if not self._check_master():
            if self.unit.is_leader():
                # Update who the current master is
                self._update_application_master()

        if not (self.unit.is_leader() and event.unit):
            return

        if not self.sentinel.in_majority:
            self.unit.status = WaitingStatus("Waiting for majority")
            event.defer()
            return

        # Update quorum for all sentinels
        self._update_quorum()

        self.unit.status = ActiveStatus()

    def _peer_relation_departed(self, event):
        """Handle relation for leaving units."""
        if not self.unit.is_leader():
            return

        if not self._check_master():
            self._update_application_master()

        # Quorum is updated beforehand, since removal of more units than current majority
        # could lead to the cluster never reaching quorum.
        logger.warning("Updating quorum")
        self._update_quorum()

        try:
            self._sentinel_failover(event.departing_unit.name)
        except Exception:
            msg = "Failover didn't finish, deferring"
            logger.error(msg)
            self.unit.status == WaitingStatus(msg)
            event.defer()
            return

        logger.warning("Resetting sentinel")
        self._reset_sentinel()

        self.unit.status = ActiveStatus()

    def _on_redis_relation_created(self, event):
        """Handle the relation created event."""
        # TODO: Update warning to point to the new interface once it is created
        logger.warning("DEPRECATION WARNING - `redis` interface is a legacy interface.")
        if not self.unit.is_leader():
            return

        self._peers.data[self.app]["enable-password"] = "false"
        self._update_layer()

        # update_layer will set a Waiting status if Pebble is not ready
        if not isinstance(self.unit.status, ActiveStatus):
            event.defer()
            return

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

        # Update the Pebble configuration Layer
        if current_layer.services != new_layer.services:
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
                    "command": f"redis-server {self._redis_extra_flags()}",
                    "user": "redis",
                    "group": "redis",
                    "startup": "enabled",
                }
            },
        }
        return Layer(layer_config)

    def _redis_extra_flags(self) -> str:
        """Generate the REDIS_EXTRA_FLAGS environment variable for the container.

        Will check config options to decide the extra commands passed at the
        redis-server service.
        """
        extra_flags = [
            f"--requirepass {self._get_password()}",
            "--bind 0.0.0.0",
            f"--masterauth {self._get_password()}",
            f"--replica-announce-ip {self.unit_pod_hostname}",
        ]

        if self._peers.data[self.app].get("enable-password", "true") == "false":
            logger.warning(
                "DEPRECATION WARNING - password off, this will be removed on later versions"
            )
            extra_flags = ["--bind 0.0.0.0"]

        if self.config["enable-tls"]:
            extra_flags += [
                f"--tls-port {REDIS_PORT}",
                "--port 0",
                "--tls-auth-clients optional",
                f"--tls-cert-file {self._storage_path}/redis.crt",
                f"--tls-key-file {self._storage_path}/redis.key",
                f"--tls-ca-cert-file {self._storage_path}/ca.crt",
            ]

        # Check that current unit is master
        if self.current_master != self.unit_pod_hostname:
            extra_flags += [f"--replicaof {self.current_master} {REDIS_PORT}"]

            if self.config["enable-tls"]:
                extra_flags += ["--tls-replication yes"]

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

    def _get_sentinel_password_action(self, event: ActionEvent) -> None:
        """Handle the get_sentinel_password event.

        Sets the result of the action with the password for Sentinel.
        """
        event.set_results({"sentinel-password": self.get_sentinel_password()})

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
    def unit_pod_hostname(self, name="") -> str:
        """Creates the pod hostname from its name."""
        return socket.getfqdn(name)

    @property
    def current_master(self) -> Optional[str]:
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

        return bool(password and self.current_master)

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

    def get_sentinel_password(self) -> Optional[str]:
        """Get the current password for sentinel.

        Returns:
            String with the password
        """
        data = self._peers.data[self.app]
        return data.get(SENTINEL_PASSWORD_KEY)

    def _store_certificates(self) -> None:
        """Copy the TLS certificates to the redis container."""
        # Get a list of valid paths
        cert_paths = list(filter(None, self._certificates))
        container = self.unit.get_container("redis")

        # Copy the files from the resources location to the redis container.
        # TODO handle error case
        for cert_path in cert_paths:
            with open(cert_path, "r") as f:
                container.push(
                    (f"{self._storage_path}/{cert_path.name}"),
                    f,
                    make_dirs=True,
                    permissions=0o600,
                    user="redis",
                    group="redis",
                )

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

    def _k8s_hostname(self, name: str) -> str:
        """Create a DNS name for a Redis unit name.

        Args:
            name: the Redis unit name, e.g. "redis-k8s-0".

        Returns:
            A string representing the hostname of the Redis unit.
        """
        unit_id = name.split("/")[1]
        return f"{self._name}-{unit_id}.{self._name}-endpoints.{self._namespace}.svc.cluster.local"

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
            decode_responses=True,
            socket_timeout=SOCKET_TIMEOUT,
        )
        try:
            yield client
        finally:
            client.close()

    def _check_master(self) -> bool:
        """Connect to the current stored master and query role."""
        with self._redis_client(hostname=self.current_master) as redis:
            try:
                result = redis.execute_command("ROLE")
            except (ConnectionError, TimeoutError) as e:
                logger.warning("Error trying to check master: {}".format(e))
                return False

            if result[0] == "master":
                return True

        return False

    def _update_application_master(self) -> None:
        """Use Sentinel to update the current master hostname."""
        info = self.sentinel.get_master_info()
        logger.debug(f"Master info: {info}")
        if info is None:
            logger.warning("Could not update current master")
            return

        self._peers.data[self.app][LEADER_HOST_KEY] = info["ip"]

    def _sentinel_failover(self, departing_unit_name: str) -> None:
        """Try to failover the current master."""
        if departing_unit_name != self.current_master:
            # No failover needed
            return

        with self.sentinel.sentinel_client() as sentinel:
            try:
                sentinel.execute_command(f"SENTINEL FAILOVER {self._name}")
            except RedisError as e:
                logger.error("Error triggering a failover: {}".format(e))
                return

        try:
            self._is_failover_finished()
        except Exception:
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(10),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _is_failover_finished(self) -> None:
        """Check if failover is still in progress."""
        logger.warning("Checking if failover is finished.")
        info = self.sentinel.get_master_info()
        if info is None:
            logger.warning("Could not check failover status")
            raise Exception

        if "failover-state" in info:
            logger.warning(
                "Failover taking place. Current status: {}".format(info["failover-state"])
            )
            raise Exception

    def _update_quorum(self) -> None:
        """Connect to all Sentinels deployed to update the quorum."""
        command = f"SENTINEL SET {self._name} quorum {self.sentinel.expected_quorum}"
        self._broadcast_sentinel_command(command)

    def _reset_sentinel(self):
        """Reset sentinel to process changes and remove unreachable servers/sentinels."""
        command = f"SENTINEL RESET {self._name}"
        self._broadcast_sentinel_command(command)

    def _broadcast_sentinel_command(self, command: str) -> None:
        """Broadcast a command to all sentinel instances.

        Args:
            command: string with the command to broadcast to all sentinels
        """
        hostnames = [self._k8s_hostname(unit.name) for unit in self._peers.units]
        # Add the own unit
        hostnames.append(self.unit_pod_hostname)

        for hostname in hostnames:
            with self.sentinel.sentinel_client(hostname=hostname) as sentinel:
                try:
                    logger.debug("Sending {} to sentinel at {}".format(command, hostname))
                    sentinel.execute_command(command)
                except (ConnectionError, TimeoutError) as e:
                    logger.error("Error connecting to instance: {} - {}".format(hostname, e))


if __name__ == "__main__":  # pragma: nocover
    main(RedisK8sCharm)
