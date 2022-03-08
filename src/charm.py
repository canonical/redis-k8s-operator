#!/usr/bin/env python3
# This file is part of the Redis k8s Charm for Juju.
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import functools
import logging

import yaml

from charms.redis_k8s.v0.redis import RedisProvides
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
        self.redis_provides = RedisProvides(self, port=DEFAULT_PORT)
        self.image = OCIImageResource(self, "redis-image")

        self.framework.observe(self.on.start, self.on_start)
        self.framework.observe(self.on.stop, self.on_stop)
        self.framework.observe(self.on.config_changed, self.configure_pod)
        self.framework.observe(self.on.upgrade_charm, self.configure_pod)
        self.framework.observe(self.on.update_status, self.update_status)

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

    def set_ready_status(self):
        logger.debug('Pod is ready.')
        self.unit.status = ActiveStatus()
        self.app.status = ActiveStatus()


if __name__ == "__main__":
    main(RedisCharm)
