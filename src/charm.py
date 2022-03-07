#!/usr/bin/env python3
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

from redis import Redis
from redis.exceptions import RedisError

from charms.redis_k8s.v0.redis import RedisProvides
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import ConnectionError

REDIS_PORT = 6379
WAITING_MESSAGE = 'Waiting for Redis...'

logger = logging.getLogger(__name__)


class RedisK8sCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.redis_provides = RedisProvides(self, port=REDIS_PORT)

        self.framework.observe(self.on.config_changed, self.config_changed)
        self.framework.observe(self.on.upgrade_charm, self.config_changed)
        self.framework.observe(self.on.update_status, self.update_status)

        self.framework.observe(self.on.check_service_action, self.check_service)

    def config_changed(self, event):
        logger.info("Beginning config_changed")
        layer_config = {
            "summary": "Redis layer",
            "description": "Redis layer",
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

        try:
            container = self.unit.get_container("redis")
            services = container.get_plan().to_dict().get("services", {})

            if services != layer_config["services"]:
                logger.debug("About to add_layer with layer_config:\n{}".format(layer_config))
                container.add_layer("redis", layer_config, combine=True)

                service = container.get_service("redis")
                if service.is_running():
                    logger.debug("Stopping service")
                    container.stop("redis")
                logger.debug("Starting service")
                container.start("redis")
        except ConnectionError:
            logger.info("Pebble is not ready, deferring event")
            event.defer()
            return

        self._redis_check()

    def update_status(self, event):
        logger.info("Beginning update_status")
        self._redis_check()

    def check_service(self, event):
        logger.info("Beginning check_service")
        results = {}
        if self._redis_check():
            results["result"] = "Service is running"
        else:
            results["result"] = "Service is not running"
        event.set_results(results)

    def _redis_check(self):
        try:
            redis = Redis()
            info = redis.info("server")
            version = info["redis_version"]
            self.unit.status = ActiveStatus()
            self.unit.set_workload_version(version)
            if self.unit.is_leader():
                self.app.status = ActiveStatus()
            return True
        except RedisError:
            self.unit.status = WaitingStatus(WAITING_MESSAGE)
            if self.unit.is_leader():
                self.app.status = WaitingStatus(WAITING_MESSAGE)
            return False


if __name__ == "__main__":  # pragma: nocover
    main(RedisK8sCharm)
