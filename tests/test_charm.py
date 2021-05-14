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

from unittest import TestCase, mock

from ops.model import ActiveStatus, Container
from ops.pebble import ServiceInfo
from ops.testing import Harness

from charm import RedisK8sCharm
from charms.redis_k8s.v0.redis import RedisProvides


class TestCharm(TestCase):
    def setUp(self):
        self.harness = Harness(RedisK8sCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_on_start_when_unit_is_not_leader(self):
        # Given
        self.harness.set_leader(False)
        # When
        self.harness.charm.on.start.emit()
        # Then
        self.assertEqual(
            self.harness.charm.unit.status,
            ActiveStatus()
        )

    def test_on_config_changed_when_unit_is_not_leader(self):
        # Given
        self.harness.set_leader(False)
        # When
        self.harness.update_config()
        # Then
        self.assertEqual(
            self.harness.charm.unit.status,
            ActiveStatus()
        )

    def test_on_upgrade_charm_when_unit_is_not_leader(self):
        # Given
        self.harness.set_leader(False)
        # When
        self.harness.charm.on.upgrade_charm.emit()
        # Then
        self.assertEqual(
            self.harness.charm.unit.status,
            ActiveStatus()
        )

    def test_config_changed_when_unit_is_leader(self):
        self.harness.set_leader(True)
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
                        "ALLOW_EMPTY_PASSWORD": "yes"
                    }
                }
            }
        }
        self.assertEqual(found_plan, expected_plan)
        container = self.harness.model.unit.get_container("redis")
        service = container.get_service("redis")
        self.assertTrue(service.is_running())
        self.assertEqual(
            self.harness.charm.unit.status,
            ActiveStatus()
        )

    def test_on_start_when_unit_is_leader_and_service_running(self):
        self.harness.set_leader(True)
        mock_info = {
            "name": "redis",
            "startup": "enabled",
            "current": "active"
        }
        mock_service = ServiceInfo.from_dict(mock_info)
        mock_container = mock.MagicMock(Container)
        mock_container.get_service.return_value = mock_service

        def mock_get_container(name):
            return mock_container

        self.harness.model.unit.get_container = mock_get_container
        self.harness.update_config()
        mock_container.stop.assert_called_once_with("redis")
        mock_container.start.assert_called_once_with("redis")

    @mock.patch.object(RedisProvides, '_bind_address')
    def test_on_relation_changed_status_when_unit_is_leader(self, bind_address):
        # Given
        self.harness.set_leader(True)
        bind_address.return_value = '10.2.1.5'

        rel_id = self.harness.add_relation('redis', 'wordpress')
        self.harness.add_relation_unit(rel_id, 'wordpress/0')
        # When
        self.harness.update_relation_data(rel_id, 'wordpress/0', {})
        rel_data = self.harness.get_relation_data(
            rel_id, self.harness.charm.unit.name
        )
        # Then
        self.assertEqual(rel_data.get('hostname'), '10.2.1.5')
        self.assertEqual(rel_data.get('port'), '6379')
