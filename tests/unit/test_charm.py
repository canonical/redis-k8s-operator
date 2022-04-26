# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest import TestCase, mock

from charms.redis_k8s.v0.redis import RedisProvides
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    Container,
    UnknownStatus,
    WaitingStatus,
)
from ops.pebble import ServiceInfo
from ops.testing import Harness
from redis import Redis
from redis.exceptions import RedisError

from charm import RedisK8sCharm


class TestCharm(TestCase):
    def setUp(self):
        self._peer_relation = "redis-peers"

        self.harness = Harness(RedisK8sCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.add_relation(self._peer_relation, self.harness.charm.app.name)

    @mock.patch.object(Redis, "info")
    def test_on_update_status_success_leader(self, info):
        self.harness.set_leader(True)
        info.return_value = {"redis_version": "6.0.11"}
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        self.assertEqual(self.harness.charm.app.status, ActiveStatus())
        self.assertEqual(self.harness.get_workload_version(), "6.0.11")

    @mock.patch.object(Redis, "info")
    def test_on_update_status_failure_leader(self, info):
        self.harness.set_leader(True)
        info.side_effect = RedisError("Error connecting to redis")
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, WaitingStatus("Waiting for Redis..."))
        self.assertEqual(self.harness.charm.app.status, WaitingStatus("Waiting for Redis..."))
        self.assertEqual(self.harness.get_workload_version(), None)

    @mock.patch.object(Redis, "info")
    def test_on_update_status_success_not_leader(self, info):
        self.harness.set_leader(False)
        info.return_value = {"redis_version": "6.0.11"}
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        # Without setting back to leader, the below throws a RuntimeError on app.status
        self.harness.set_leader(True)
        self.assertEqual(self.harness.charm.app.status, UnknownStatus())
        self.assertEqual(self.harness.get_workload_version(), "6.0.11")

    @mock.patch.object(Redis, "info")
    def test_on_update_status_failure_not_leader(self, info):
        self.harness.set_leader(False)
        info.side_effect = RedisError("Error connecting to redis")
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, WaitingStatus("Waiting for Redis..."))
        # Without setting back to leader, the below throws a RuntimeError on app.status
        self.harness.set_leader(True)
        self.assertEqual(self.harness.charm.app.status, UnknownStatus())
        self.assertEqual(self.harness.get_workload_version(), None)

    @mock.patch.object(Redis, "info")
    def test_config_changed_when_unit_is_leader_status_success(self, info):
        self.harness.set_leader(True)
        info.return_value = {"redis_version": "6.0.11"}
        self.harness.update_config()
        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()
        expected_plan = {
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": "/usr/local/bin/start-redis.sh redis-server",
                    "startup": "enabled",
                    "environment": {
                        "REDIS_PASSWORD": self.harness.charm._get_password(),
                        "REDIS_EXTRA_FLAGS": "",
                    },
                }
            },
        }
        self.assertEqual(found_plan, expected_plan)
        container = self.harness.model.unit.get_container("redis")
        service = container.get_service("redis")
        self.assertTrue(service.is_running())
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        self.assertEqual(self.harness.charm.app.status, ActiveStatus())
        self.assertEqual(self.harness.get_workload_version(), "6.0.11")

    @mock.patch.object(Redis, "info")
    def test_config_changed_when_unit_is_leader_status_failure(self, info):
        self.harness.set_leader(True)
        info.side_effect = RedisError("Error connecting to redis")
        self.harness.update_config()
        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()
        expected_plan = {
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": "/usr/local/bin/start-redis.sh redis-server",
                    "startup": "enabled",
                    "environment": {
                        "REDIS_PASSWORD": self.harness.charm._get_password(),
                        "REDIS_EXTRA_FLAGS": "",
                    },
                }
            },
        }
        self.assertEqual(found_plan, expected_plan)
        container = self.harness.model.unit.get_container("redis")
        service = container.get_service("redis")
        self.assertTrue(service.is_running())
        self.assertEqual(self.harness.charm.unit.status, WaitingStatus("Waiting for Redis..."))
        self.assertEqual(self.harness.charm.app.status, WaitingStatus("Waiting for Redis..."))
        self.assertEqual(self.harness.get_workload_version(), None)

    @mock.patch.object(Redis, "info")
    def test_config_changed_pebble_error(self, info):
        self.harness.set_leader(True)
        mock_container = mock.MagicMock(Container)
        mock_container.can_connect.return_value = False

        def mock_get_container(name):
            return mock_container

        self.harness.model.unit.get_container = mock_get_container
        self.harness.update_config()
        mock_container.add_layer.assert_not_called()
        mock_container.restart.assert_not_called()
        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for Pebble in workload container"),
        )
        self.assertEqual(self.harness.charm.app.status, UnknownStatus())
        self.assertEqual(self.harness.get_workload_version(), None)
        # TODO - test for the event being deferred

    @mock.patch.object(Redis, "info")
    def test_config_changed_when_unit_is_leader_and_service_is_running(self, info):
        self.harness.set_leader(True)
        info.return_value = {"redis_version": "6.0.11"}
        mock_info = {"name": "redis", "startup": "enabled", "current": "active"}
        mock_service = ServiceInfo.from_dict(mock_info)
        mock_container = mock.MagicMock(Container)
        mock_container.get_service.return_value = mock_service

        def mock_get_container(name):
            return mock_container

        self.harness.model.unit.get_container = mock_get_container
        self.harness.update_config()
        mock_container.restart.assert_called_once_with("redis")
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        self.assertEqual(self.harness.charm.app.status, ActiveStatus())
        self.assertEqual(self.harness.get_workload_version(), "6.0.11")

    def test_password_on_leader_elected(self):
        # Assert that there is no password in the peer relation.
        self.assertFalse(self.harness.charm._get_password())

        # Check that a new password was generated on leader election.
        self.harness.set_leader()
        admin_password = self.harness.charm._get_password()
        self.assertTrue(admin_password)

        # Trigger a new leader election and check that the password is still the same.
        self.harness.set_leader(False)
        self.harness.set_leader()
        self.assertEqual(
            self.harness.charm._get_password(),
            admin_password,
        )

    @mock.patch.object(RedisProvides, "_bind_address")
    def test_on_relation_changed_status_when_unit_is_leader(self, bind_address):
        # Given
        self.harness.set_leader(True)
        bind_address.return_value = "10.2.1.5"

        rel_id = self.harness.add_relation("redis", "wordpress")
        self.harness.add_relation_unit(rel_id, "wordpress/0")
        # When
        self.harness._emit_relation_changed(rel_id, "wordpress/0")
        rel_data = self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)
        # Then
        self.assertEqual(rel_data.get("hostname"), "10.2.1.5")
        self.assertEqual(rel_data.get("port"), "6379")

    @mock.patch("charm.RedisK8sCharm._store_certificates")
    def test_attach_resource(self, _store_certificates):
        # Check that there are no resources initially
        self.assertEqual(self.harness.charm._certificates, [None, None, None])

        self.harness.add_resource("cert-file", "")
        self.harness.add_resource("key-file", "")
        self.harness.add_resource("ca-cert-file", "")

        # After adding them, check that the property returns paths for the three of them
        self.assertTrue(None not in self.harness.charm._certificates)

        self.harness.charm.on.upgrade_charm.emit()
        _store_certificates.assert_called()

    def test_blocked_on_enable_tls_with_no_certificates(self):
        self.harness.update_config({"enable-tls": True})
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Not enough certificates found")
        )

    @mock.patch("charm.RedisK8sCharm._store_certificates")
    @mock.patch.object(Redis, "info")
    def test_active_on_enable_tls_with_certificates(self, info, _store_certificates):
        self.harness.set_leader(True)
        info.return_value = {"redis_version": "6.0.11"}

        self.harness.add_resource("cert-file", "")
        self.harness.add_resource("key-file", "")
        self.harness.add_resource("ca-cert-file", "")

        self.harness.charm.on.upgrade_charm.emit()

        _store_certificates.assert_called()

        self.harness.update_config({"enable-tls": True})

        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()
        extra_flags = [
            "--tls-port 6379",
            "--port 0",
            "--tls-auth-clients optional",
            "--tls-cert-file /var/lib/redis/redis.crt",
            "--tls-key-file /var/lib/redis/redis.key",
            "--tls-ca-cert-file /var/lib/redis/ca.crt",
        ]
        expected_plan = {
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": "/usr/local/bin/start-redis.sh redis-server",
                    "startup": "enabled",
                    "environment": {
                        "REDIS_PASSWORD": self.harness.charm._get_password(),
                        "REDIS_EXTRA_FLAGS": " ".join(extra_flags),
                    },
                }
            },
        }

        self.assertEqual(found_plan, expected_plan)
        container = self.harness.model.unit.get_container("redis")
        service = container.get_service("redis")
        self.assertTrue(service.is_running())
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        self.assertEqual(self.harness.charm.app.status, ActiveStatus())
        self.assertEqual(self.harness.get_workload_version(), "6.0.11")
