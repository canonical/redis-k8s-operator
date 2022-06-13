#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


from pathlib import Path

import yaml

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
STORAGE_PATH = METADATA["storage"]["database"]["location"]
TLS_RESOURCES = {
    "cert-file": "tests/tls/redis.crt",
    "key-file": "tests/tls/redis.key",
    "ca-cert-file": "tests/tls/ca.crt",
}
APPLICATION_DATA = {
    "leader-host": "leader-host",
    "redis-password": "password",
}
NUM_UNITS = 2
