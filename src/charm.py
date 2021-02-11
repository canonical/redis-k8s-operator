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

import functools
import logging

import yaml
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from client import RedisClient
from log_adapter import CustomAdapter
from pod_spec import PodSpecBuilder

WAITING_FOR_REDIS_MSG = 'Waiting for Redis ...'

logger = CustomAdapter(logging.getLogger(__name__), {'prefix': 'redis-operator:charm'})

# We expect the redis container to use the default port
DEFAULT_PORT = 6379


def log_event_handler(method):
    @functools.wraps(method)
    def decorated(self, event):
        logger.debug("Running {}".format(method.__name__))
        try:
            return method(self, event)
        finally:
            logger.debug("Completed {}".format(method.__name__))

    return decorated


class RedisCharm(CharmBase):
    state = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        logger.debug('Initializing charm')

        self.redis = RedisClient(host=self.model.app.name, port=DEFAULT_PORT)
        self.image = OCIImageResource(self, "redis-image")

        self.framework.observe(self.on.start, self.on_start)
        self.framework.observe(self.on.stop, self.on_stop)
        self.framework.observe(self.on.config_changed, self.configure_pod)
        self.framework.observe(self.on.upgrade_charm, self.configure_pod)
        self.framework.observe(self.on.update_status, self.update_status)
        self.framework.observe(self.on["datastore"].relation_changed, self.relation_changed)

    @log_event_handler
    def on_start(self, event):
        """Initialize Redis.

        This event handler is deferred if initialization of Redis fails.
        """
        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        if not self.redis.is_ready():
            self.unit.status = WaitingStatus(WAITING_FOR_REDIS_MSG)
            logger.debug("{}: deferring on_start".format(WAITING_FOR_REDIS_MSG))
            event.defer()
            return

        self.set_ready_status()

    @log_event_handler
    def on_stop(self, _):
        """Mark terminating unit as inactive.
        """
        self.redis.close()
        self.unit.status = MaintenanceStatus('Pod is terminating.')

    @log_event_handler
    def configure_pod(self, event):
        """Applies the pod configuration.
        """
        if not self.unit.is_leader():
            logger.debug("Spec changes ignored by non-leader")
            self.unit.status = ActiveStatus()
            return

        self.unit.status = WaitingStatus("Fetching image information ...")
        try:
            image_info = self.image.fetch()
        except OCIImageResourceError:
            self.unit.status = BlockedStatus(
                "Error fetching image information.")
            return

        # Build Pod spec
        builder = PodSpecBuilder(
            name=self.model.app.name,
            port=DEFAULT_PORT,
            image_info=image_info,
        )

        spec = builder.build_pod_spec()
        logger.debug("Pod spec: \n{}".format(yaml.dump(spec)))

        # Applying pod spec. If the spec hasn't changed, this has no effect.
        logger.debug("Applying pod spec.")
        self.model.pod.set_spec(spec)

        if not self.redis.is_ready():
            self.unit.status = WaitingStatus(WAITING_FOR_REDIS_MSG)
            logger.debug("{}: deferring configure_pod".format(WAITING_FOR_REDIS_MSG))
            event.defer()
            return

        self.set_ready_status()

    @log_event_handler
    def update_status(self, _):
        """Set status for all units.

        Status may be
        - Redis API server not reachable (service is not ready),
        - Ready
        """
        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        if not self.redis.is_ready():
            self.unit.status = WaitingStatus(WAITING_FOR_REDIS_MSG)
            return

        self.set_ready_status()

    @log_event_handler
    def relation_changed(self, event):
        """This event handler pass the host and port to the remote unit.
         Any Redis client is provided with the following information
        - Redis host
        - Redis port

        Using this information a client can establish a connection with
        Redis, for instances using the redis Python library.
        """

        if not self.unit.is_leader():
            logger.debug("Relation changes ignored by non-leader")
            return

        event.relation.data[self.unit]['hostname'] = str(self.bind_address(event))
        event.relation.data[self.unit]['port'] = str(DEFAULT_PORT)
        # The reactive Redis charm exposes also 'password'. When tackling
        # https://github.com/canonical/redis-operator/issues/7 add 'password'
        # field so that it matches the exposed interface information from it.
        # event.relation.data[self.unit]['password'] = ''

    def bind_address(self, event):
        relation = self.model.get_relation(event.relation.name, event.relation.id)
        if address := self.model.get_binding(relation).network.bind_address:
            return address
        return self.app.name

    def set_ready_status(self):
        logger.debug('Pod is ready.')
        self.unit.status = ActiveStatus()
        self.app.status = ActiveStatus()


if __name__ == "__main__":
    main(RedisCharm)
