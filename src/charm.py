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

from charms.redis_k8s.v0.redis import RedisProvides
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus

# We expect the redis container to use the default port
DEFAULT_PORT = 6379

logger = logging.getLogger(__name__)


class RedisK8sCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        logger.debug('Initializing charm')

        self.redis_provides = RedisProvides(self, port=DEFAULT_PORT)

        self.framework.observe(self.on.start, self.configure_pod)
        self.framework.observe(self.on.config_changed, self.configure_pod)
        self.framework.observe(self.on.upgrade_charm, self.configure_pod)

    def configure_pod(self, event):
        """Applies the pod configuration.
        """
        if not self.unit.is_leader():
            logger.info("Spec changes ignored by non-leader")
            self.unit.status = ActiveStatus()
            return

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

        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(RedisK8sCharm)
