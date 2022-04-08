# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest import mock

import redis

from client import RedisClient


class TestClient(unittest.TestCase):
    def setUp(self) -> None:
        self.client = RedisClient("host", 1234)

    @mock.patch("redis.Redis")
    def test_when_redis_can_ping_then_redis_is_ready(self, mock_redis):
        # Given
        redis_instance = mock_redis.return_value
        redis_instance.ping.return_value = True

        # When
        is_ready = self.client.is_ready()

        # Then
        self.assertTrue(is_ready)

    @mock.patch("redis.Redis")
    def test_when_redis_cannot_ping_then_redis_is_not_ready(self, mock_redis):
        # Given
        redis_instance = mock_redis.return_value
        redis_instance.ping.return_value = False

        # When
        is_ready = self.client.is_ready()

        # Then
        self.assertFalse(is_ready)

    @mock.patch("redis.Redis")
    def test_when_redis_fails_to_connect_then_redis_is_not_ready(self, mock_redis):
        # Given
        mock_redis.side_effect = redis.exceptions.ConnectionError()

        # When
        with self.assertLogs(level="WARNING") as logger:
            is_ready = self.client.is_ready()

            # Then
            self.assertFalse(is_ready)
            self.assertEqual(
                logger.output,
                ["WARNING:client:[redis-operator:client] Unable to connect to Redis: "])
