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

from typing import Dict, List

from charmhelpers.core import hookenv


class PodSpecBuilder:
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

        # vol_config = [
        #     {"name": "charm-secrets", "mountPath": "/charm-secrets", "secret": {"name": "charm-secrets"}},
        #     {"name": "var-run-postgresql", "mountPath": "/var/run/postgresql", "emptyDir": {"medium": "Memory"}},
        # ]

        spec = {
            "version": 3,
            "containers": [{
                "name": self.name,
                "imageDetails": self.image_info,
                "imagePullPolicy": "Always",
                "ports": self._build_port_spec(),
                "envConfig": self._build_env_conf_spec(),
                # "volumeConfig": vol_config,
                "kubernetes": {
                    "readinessProbe": self._build_readiness_spec(),
                    "livenessProbe": self._build_liveness_spec()
                },
            }],
            "kubernetesResources": {},
        }

        return spec

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

    def _build_env_conf_spec(self) -> Dict:
        config_fields = {
            "JUJU_NODE_NAME": "spec.nodeName",
            "JUJU_POD_NAME": "metadata.name",
            "JUJU_POD_NAMESPACE": "metadata.namespace",
            "JUJU_POD_IP": "status.podIP",
        }
        env_config = {k: {"field": {"path": p, "api-version": "v1"}} for k, p in config_fields.items()}

        env_config["JUJU_EXPECTED_UNITS"] = " ".join(self.expected_units())
        env_config["JUJU_APPLICATION"] = self.name

        return env_config

    @staticmethod
    def expected_units() -> List[str]:
        # Goal state looks like this:
        #
        # relations: {}
        # units:
        #   redis/0:
        #     since: '2020-08-31 11:05:32Z'
        #     status: active
        #   redis/1:
        #     since: '2020-08-31 11:05:54Z'
        #     status: maintenance
        return sorted(hookenv.goal_state().get("units", {}).keys(), key=lambda x: int(x.split("/")[-1]))
