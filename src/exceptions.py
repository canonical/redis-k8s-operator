#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Module with custom exceptions related to the Redis charm."""


class RedisOperatorError(Exception):
    """Base class for exceptions in this module."""

    def __repr__(self):
        """String representation of the Error class."""
        return "<{}.{} {}>".format(type(self).__module__, type(self).__name__, self.args)

    @property
    def name(self):
        """Return a string representation of the model plus class."""
        return "<{}.{}>".format(type(self).__module__, type(self).__name__)

    @property
    def message(self):
        """Return the message passed as an argument."""
        return self.args[0]


class RedisFailoverInProgressError(RedisOperatorError):
    """Exception raised when creating a user fails."""


class RedisFailoverCheckError(RedisOperatorError):
    """Exception raised when failover status cannot be checked."""
