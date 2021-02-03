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
            self.redis = self._get_client()
            if self.redis.ping():
                logger.debug("We can ping Redis, service is ready.")
                return True
            logger.debug("Not able to ping Redis.")
            return False
        except redis.exceptions.ConnectionError as exc:
            logger.warning("Unable to connect to Redis: {}".format(exc))
        return False

    def _get_client(self) -> redis.Redis:
        return redis.Redis(host=self.host, port=self.port)

    def close(self):
        if self.redis:
            self.redis.client().close()
