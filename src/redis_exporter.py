#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


"""Charm code for exporter service.

Redis exporter exposes metrics for Prometheus.
"""

import logging

from ops.framework import Object
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class Exporter(Object):
    """Redis exporter."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "exporter")

        self.charm = charm
        self.framework.observe(charm.on.exporter_pebble_ready, self.exporter_pebble_ready)

    def exporter_pebble_ready(self, event) -> None:
        """Handle pebble ready."""
        self._update_exporter_layer()

        # update layer should leave the unit in active status
        if not isinstance(self.charm.unit.status, ActiveStatus):
            event.defer()
            return

    def _update_exporter_layer(self) -> None:
        container = self.charm.unit.get_container("exporter")

        if not container.can_connect():
            self.charm.unit.status = WaitingStatus("Waiting for Pebble in exporter container")
            return

        if not self.charm._valid_app_databag():
            self.charm.unit.status = WaitingStatus("Databag has not been populated")
            return

        # Create the new config layer
        new_layer = self._exporter_layer()

        # Update the Pebble configuration Layer
        container.add_layer("exporter", new_layer, combine=True)
        container.replan()

    def _exporter_layer(self) -> Layer:
        """asd."""
        layer_config = {
            "summary": "Exporter layer",
            "description": "Redis exporter layer",
            "services": {
                "exporter": {
                    "override": "replace",
                    "summary": "Redis exporter service",
                    "command": "/redis_exporter",
                    # "user": "redis",
                    # "group": "redis",
                    "startup": "enabled",
                    "environment": {
                        "REDIS_PASSWORD": self.charm._get_password(),
                    },
                }
            },
        }
        return Layer(layer_config)
