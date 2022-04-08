# This file is part of the Redis k8s Charm for Juju.
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from typing import Dict, List


class PodSpecBuilder:
    """
    This class provides the methods to build the pod spec.
    """

    def __init__(
            self,
            name: str,
            port: int = 6379,
            image_info: Dict = None
    ):
        if not image_info:
            image_info = {}
        self.name = name
        self.port = port
        self.image_info = image_info

    def build_pod_spec(self) -> Dict:
        """Set up and return our full pod spec."""

        # TODO: If persistence is needed, configure it below and uncomment it
        # in the spec dictionary
        # vol_config = [
        #   {"name": "var-run-redis",
        #    "mountPath": "/var/run/redis",
        #    "emptyDir": {"medium": "Memory"}}
        # ]

        spec = {
            "version": 3,
            "containers": [{
                "name": self.name,
                "imageDetails": self.image_info,
                "imagePullPolicy": "Always",
                "ports": self._build_port_spec(),
                # "volumeConfig": vol_config,
                "envConfig": self._build_env_config(),
                "kubernetes": {
                    "readinessProbe": self._build_readiness_spec(),
                    "livenessProbe": self._build_liveness_spec()
                },
            }],
            "kubernetesResources": {},
        }

        return spec

    def _build_env_config(self):
        return {
            # https://github.com/canonical/redis-operator/issues/7
            "ALLOW_EMPTY_PASSWORD": "yes"
        }

    def _build_liveness_spec(self) -> Dict:
        return {
            "exec": {"command": ["redis-cli", "ping"]},
            "initialDelaySeconds": 45,
            "timeoutSeconds": 5,
        }

    def _build_readiness_spec(self) -> Dict:
        return {
            "tcpSocket": {
                "port": self.port
            },
            "initialDelaySeconds": 10,
            "periodSeconds": 5
        }

    def _build_port_spec(self) -> List:
        return [{
            "name": "redis",
            "containerPort": self.port,
            "protocol": "TCP"
        }]
