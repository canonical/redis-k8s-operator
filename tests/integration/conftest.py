#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
import websockets
from pytest_operator.plugin import OpsTest, check_deps


@pytest.fixture(scope="module")
@pytest.mark.asyncio
async def ops_test(request, tmp_path_factory):
    check_deps("juju", "charmcraft")
    ops_test = OpsTest(request, tmp_path_factory)
    await ops_test._setup_model()
    OpsTest._instance = ops_test
    yield ops_test
    OpsTest._instance = None

    # FIXME: this is necessary because (for some reason) ops_test raises.
    #  cf: https://github.com/charmed-kubernetes/pytest-operator/issues/71
    try:
        await ops_test._cleanup_models()
    except websockets.exceptions.ConnectionClosed:
        print("ignored a websockets.exceptions.ConnectionClosed error")
