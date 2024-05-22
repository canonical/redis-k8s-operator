#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest import TestCase, mock

from charms.redis_k8s.v0.redis import RedisProvides
from ops.charm import RelationDepartedEvent
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

APPLICATION_DATA = {
    "leader-host": "leader-host",
    "redis-password": "password",
}


class TestCharm(TestCase):
    def setUp(self):
        self._peer_relation = "redis-peers"

        self.harness = Harness(RedisK8sCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_can_connect("redis", True)
        self.harness.set_can_connect("sentinel", True)
        self.harness.begin()
        self.harness.add_relation(self._peer_relation, self.harness.charm.app.name)

    @mock.patch.object(Redis, "execute_command")
    @mock.patch.object(Redis, "info")
    def test_on_update_status_success_leader(self, info, command):
        self.harness.set_leader(True)
        command.return_value = ["ip", APPLICATION_DATA["leader-host"]]
        info.return_value = {"redis_version": "6.0.11"}
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        self.assertEqual(self.harness.charm.app.status, ActiveStatus())
        self.assertEqual(self.harness.get_workload_version(), "6.0.11")

    @mock.patch.object(Redis, "execute_command")
    @mock.patch.object(Redis, "info")
    def test_on_update_status_failure_leader(self, info, command):
        self.harness.set_leader(True)
        command.return_value = ["ip", APPLICATION_DATA["leader-host"]]
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
        self.harness.charm.on.update_status.emit()
        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()
        extra_flags = [
            f"--requirepass {self.harness.charm._get_password()}",
            "--bind 0.0.0.0",
            f"--masterauth {self.harness.charm._get_password()}",
            f"--replica-announce-ip {self.harness.charm.unit_pod_hostname}",
            "--logfile /var/log/redis/redis-server.log",
        ]
        expected_plan = {
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": f"redis-server {' '.join(extra_flags)}",
                    "user": "redis",
                    "group": "redis",
                    "startup": "enabled",
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
        self.harness.charm.on.update_status.emit()
        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()
        extra_flags = [
            f"--requirepass {self.harness.charm._get_password()}",
            "--bind 0.0.0.0",
            f"--masterauth {self.harness.charm._get_password()}",
            f"--replica-announce-ip {self.harness.charm.unit_pod_hostname}",
            "--logfile /var/log/redis/redis-server.log",
        ]
        expected_plan = {
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": f"redis-server {' '.join(extra_flags)}",
                    "user": "redis",
                    "group": "redis",
                    "startup": "enabled",
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
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

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

    @mock.patch.object(RedisK8sCharm, "_is_failover_finished")
    def test_password_on_leader_elected(self, _):
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

    @mock.patch.object(RedisProvides, "_get_master_ip")
    def test_on_relation_changed_status_when_unit_is_leader(self, get_master_ip):
        # Given
        self.harness.set_leader(True)
        get_master_ip.return_value = "10.2.1.5"

        rel_id = self.harness.add_relation("redis", "wordpress")
        self.harness.add_relation_unit(rel_id, "wordpress/0")
        # When
        self.harness._emit_relation_changed(rel_id, "wordpress/0")
        rel_data = self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)
        # Then
        self.assertEqual(rel_data.get("hostname"), "10.2.1.5")
        self.assertEqual(rel_data.get("port"), "6379")

    def test_pebble_layer_on_relation_created(self):
        self.harness.set_leader(True)

        # Create a relation using 'redis' interface
        rel_id = self.harness.add_relation("redis", "wordpress")
        self.harness.add_relation_unit(rel_id, "wordpress/0")
        self.harness._emit_relation_created("redis", rel_id, "wordpress/0")

        # Check that the resulting plan does not have a password
        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()
        extra_flags = [
            "--bind 0.0.0.0",
            f"--replica-announce-ip {self.harness.charm.unit_pod_hostname}",
            "--protected-mode no",
            "--logfile /var/log/redis/redis-server.log",
        ]
        expected_plan = {
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": f"redis-server {' '.join(extra_flags)}",
                    "user": "redis",
                    "group": "redis",
                    "startup": "enabled",
                }
            },
        }
        self.assertEqual(found_plan, expected_plan)

    @mock.patch("charm.RedisK8sCharm._store_certificates")
    def test_attach_resource(self, _store_certificates):
        # Check that there are no resources initially
        self.assertEqual(self.harness.charm._certificates, [None, None, None])

        self.harness.add_resource("cert-file", "")
        self.harness.add_resource("key-file", "")
        self.harness.add_resource("ca-cert-file", "")

        # After adding them, check that the property returns paths for the three of them
        self.assertTrue(None not in self.harness.charm._certificates)

        self.harness.set_leader(True)
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
        self.harness.charm.on.update_status.emit()

        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()
        extra_flags = [
            f"--requirepass {self.harness.charm._get_password()}",
            "--bind 0.0.0.0",
            f"--masterauth {self.harness.charm._get_password()}",
            f"--replica-announce-ip {self.harness.charm.unit_pod_hostname}",
            "--logfile /var/log/redis/redis-server.log",
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
                    "command": f"redis-server {' '.join(extra_flags)}",
                    "user": "redis",
                    "group": "redis",
                    "startup": "enabled",
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

    @mock.patch.object(Redis, "execute_command")
    def test_non_leader_unit_as_replica(self, execute_command):
        # Custom responses to Redis `execute_command` call
        def my_side_effect(value: str):
            mapping = {
                f"SENTINEL CKQUORUM {self.harness.charm._name}": "OK",
                f"SENTINEL MASTER {self.harness.charm._name}": [
                    "ip",
                    APPLICATION_DATA["leader-host"],
                    "flags",
                    "master",
                ],
            }
            return mapping.get(value)

        execute_command.side_effect = my_side_effect

        rel = self.harness.charm.model.get_relation(self._peer_relation)
        # Trigger peer_relation_joined/changed
        self.harness.add_relation_unit(rel.id, "redis-k8s/1")
        # Simulate an update to the application databag made by the leader unit
        self.harness.update_relation_data(rel.id, "redis-k8s", APPLICATION_DATA)
        # A pebble ready event will set the non-leader unit with the correct information
        self.harness.container_pebble_ready("redis")

        leader_hostname = APPLICATION_DATA["leader-host"]
        redis_port = 6379
        extra_flags = [
            f"--requirepass {self.harness.charm._get_password()}",
            "--bind 0.0.0.0",
            f"--masterauth {self.harness.charm._get_password()}",
            f"--replica-announce-ip {self.harness.charm.unit_pod_hostname}",
            "--logfile /var/log/redis/redis-server.log",
            f"--replicaof {leader_hostname} {redis_port}",
        ]
        expected_plan = {
            "services": {
                "redis": {
                    "override": "replace",
                    "summary": "Redis service",
                    "command": f"redis-server {' '.join(extra_flags)}",
                    "user": "redis",
                    "group": "redis",
                    "startup": "enabled",
                }
            },
        }
        found_plan = self.harness.get_container_pebble_plan("redis").to_dict()

        self.assertEqual(expected_plan, found_plan)
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @mock.patch.object(Redis, "execute_command")
    def test_application_data_update_after_failover(self, execute_command):
        # Custom responses to Redis `execute_command` call
        def my_side_effect(value: str):
            mapping = {
                f"SENTINEL CKQUORUM {self.harness.charm._name}": "OK",
                f"SENTINEL MASTER {self.harness.charm._name}": [
                    "ip",
                    "different-leader",
                    "flags",
                    "s_down",
                ],
            }
            return mapping.get(value)

        execute_command.side_effect = my_side_effect

        self.harness.set_leader(True)
        rel = self.harness.charm.model.get_relation(self._peer_relation)
        # Trigger peer_relation_joined/changed
        self.harness.add_relation_unit(rel.id, "redis-k8s/1")
        # Simulate an update to the application databag made by the leader unit
        self.harness.update_relation_data(rel.id, "redis-k8s", APPLICATION_DATA)

        # NOTE: On config changed, charm will be updated with APPLICATION_DATA. But a
        # call to `execute_command(SENTINEL MASTER redis-k8s)` will return `different_leader`
        # when checking the master, simulating that sentinel triggered failover in between
        # charm events.
        self.harness._emit_relation_changed(rel.id, "redis-k8s")

        updated_data = self.harness.get_relation_data(rel.id, "redis-k8s")
        self.assertEqual(updated_data["leader-host"], "different-leader")

        # Reset the application data to the initial state
        self.harness.update_relation_data(rel.id, "redis-k8s", APPLICATION_DATA)

        # Now check that a pod reschedule will also result in updated information
        self.harness.charm.on.upgrade_charm.emit()

        updated_data = self.harness.get_relation_data(rel.id, "redis-k8s")
        self.assertEqual(updated_data["leader-host"], "different-leader")

    @mock.patch.object(Redis, "execute_command")
    def test_forced_failover_when_unit_departed_is_master(self, execute_command):
        # Custom responses to Redis `execute_command` call
        def my_side_effect(value: str):
            mapping = {
                f"SENTINEL CKQUORUM {self.harness.charm._name}": "OK",
                f"SENTINEL MASTER {self.harness.charm._name}": [
                    "ip",
                    self.harness.charm._k8s_hostname("redis-k8s/1"),
                    "flags",
                    "master",
                ],
            }
            return mapping.get(value)

        execute_command.side_effect = my_side_effect

        self.harness.set_leader(True)
        rel = self.harness.charm.model.get_relation(self._peer_relation)
        # Simulate an update to the application databag made by the leader unit
        self.harness.update_relation_data(rel.id, "redis-k8s", APPLICATION_DATA)
        # Add and remove a unit that sentinel will simulate as current master
        self.harness.add_relation_unit(rel.id, "redis-k8s/1")

        rel = self.harness.charm.model.get_relation(self._peer_relation)
        # Workaround ops.testing not setting `departing_unit` in v1.5.0
        # ref https://github.com/canonical/operator/pull/790
        with mock.patch.object(
            RelationDepartedEvent, "departing_unit", new_callable=mock.PropertyMock
        ) as mock_departing_unit:
            mock_departing_unit.return_value = list(rel.units)[0]
            self.harness.remove_relation_unit(rel.id, "redis-k8s/1")

        execute_command.assert_called_with("SENTINEL RESET redis-k8s")
