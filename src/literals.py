#!/usr/bin/env python3
# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.

"""Literals used by the Redis charm."""

WAITING_MESSAGE = "Waiting for Redis..."
PEER = "redis-peers"
PEER_PASSWORD_KEY = "redis-password"
LEADER_HOST_KEY = "leader-host"

REDIS_PORT = 6379
SENTINEL_PORT = 26379

CONFIG_PATH = "/etc/redis/"
REDIS_CONFIG_PATH = f"{CONFIG_PATH}/redis.conf"
SENTINEL_CONFIG_PATH = f"{CONFIG_PATH}/sentinel.conf"
