#!/usr/bin/env python3
# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.

"""Helper methods to create a redis connection."""

from redis import Redis


def redis_client(
    password_enabled: str,
    password: str,
    host="localhost",
    ssl=False,
    storage_path="") -> Redis:
    """Helper class that creates a Redis connection with variable parameters.

    Args:
        password_enabled: str to check if the connection needs a password (DEPRECATE)
        password: string with the database password
        host: string with the hostname to connect to
        ssl: boolean, true if the connection requires TLS encryption
        storage_path: string with the path to the container mounted volume

    Returns:
        Redis class with the connection
    """
    # NOTE: This check will become deprecated in the future
    if password_enabled == "true":
        redis = Redis(host=host, password=password)
    elif ssl:
        ca_path = f"{storage_path}/ca.crt"
        redis = Redis(host=host, password=password, ssl=ssl, ssl_ca_certs=ca_path)
    else:
        redis = Redis(host=host)

    return redis
