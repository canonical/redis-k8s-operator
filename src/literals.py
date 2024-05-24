#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals used by the Redis charm."""

WAITING_MESSAGE = "Waiting for Redis..."
PEER = "redis-peers"
REDIS_REL_NAME = "redis"
PEER_PASSWORD_KEY = "redis-password"
SENTINEL_PASSWORD_KEY = "sentinel-password"
LEADER_HOST_KEY = "leader-host"
SOCKET_TIMEOUT = 1

REDIS_PORT = 6379
SENTINEL_PORT = 26379

CONFIG_DIR = "/etc/redis-server"
SENTINEL_CONFIG_PATH = f"{CONFIG_DIR}/sentinel.conf"
