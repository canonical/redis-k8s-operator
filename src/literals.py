#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals used by the Redis charm."""

WAITING_MESSAGE = "Waiting for Redis..."
PEER = "redis-peers"
PEER_PASSWORD_KEY = "redis-password"
SENTINEL_PASSWORD_KEY = "sentinel-password"
LEADER_HOST_KEY = "leader-host"

REDIS_PORT = 6379
SENTINEL_PORT = 26379

CONFIG_PATH = "/etc/redis"
REDIS_CONFIG_PATH = f"{CONFIG_PATH}/redis.conf"
SENTINEL_CONFIG_PATH = f"{CONFIG_PATH}/sentinel.conf"
