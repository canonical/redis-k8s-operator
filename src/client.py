# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import redis

from log_adapter import CustomAdapter

logger = CustomAdapter(logging.getLogger(__name__), {'prefix': 'redis-operator:client'})


class RedisClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.redis: redis.Redis = None

    def is_ready(self) -> bool:
        """Checks whether Redis is ready, no only accepting connections
        but can also respond to a simple PING request.

        :return: whether Redis is ready to be receive requests.
        """
        try:
            self.redis = redis.Redis(host=self.host, port=self.port)
            if self.redis.ping():
                logger.debug("We can ping Redis, service is ready.")
                return True
            logger.debug("Not able to ping Redis.")
            return False
        except redis.exceptions.ConnectionError as exc:
            logger.warning("Unable to connect to Redis: {}".format(exc))
        return False

    def close(self):
        if self.redis:
            self.redis.client().close()
