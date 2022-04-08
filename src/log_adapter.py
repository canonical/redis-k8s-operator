# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging


class CustomAdapter(logging.LoggerAdapter):
    """
    This adapter prefix the log messages by a given 'prefix' key.
    """

    def process(self, msg, kwargs):
        return '[%s] %s' % (self.extra['prefix'], msg), kwargs
