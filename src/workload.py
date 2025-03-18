#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kafka Connect workload class and methods."""

import fnmatch
import logging
import os
import socket
from contextlib import closing
from typing import BinaryIO, Iterable

from ops import Container, pebble
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed
from typing_extensions import override

from core.workload import Paths, WorkloadBase
from literals import (
    CHARM_KEY,
    CONFIG_DIR,
    GROUP,
    JMX_EXPORTER_PORT,
    LOG_SENSITIVE_OUTPUT,
    SERVICE_NAME,
    USER,
)

logger = logging.getLogger(__name__)


class K8sPaths(Paths):
    """Object to store common paths for Kafka Connect worker in K8s environment."""

    @property
    @override
    def jmx_prometheus_javaagent(self) -> str:
        """Path to JMX Prometheus exporter java agent."""
        return "/opt/kafka/libs/jmx_prometheus_javaagent.jar"

    @property
    @override
    def logs_dir(self) -> str:
        """Path to logs dir in K8s."""
        return "/var/log/connect"


class Workload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka Connect Container."""

    service: str = SERVICE_NAME

    def __init__(self, container: Container) -> None:
        self.container = container
        self.paths = K8sPaths(CONFIG_DIR)

    @override
    def start(self) -> None:
        self.container.add_layer(CHARM_KEY, self.layer, combine=True)
        self.container.restart(self.service)

    @override
    def stop(self) -> None:
        self.container.stop(self.service)

    @override
    def restart(self) -> None:
        self.start()

    @override
    def read(self, path: str) -> list[str]:
        if not self.container.exists(path):
            return []
        else:
            with self.container.pull(path) as f:
                content = f.read().split("\n")

        return content

    @override
    def write(self, content: str | BinaryIO, path: str, mode: str = "w") -> None:
        self.container.push(path, content, make_dirs=True)

    @override
    def exec(
        self,
        command: list[str] | str,
        env: dict[str, str] | None = None,
        working_dir: str | None = None,
        sensitive: bool = False,
    ) -> str:
        should_log = not sensitive or LOG_SENSITIVE_OUTPUT
        command = command if isinstance(command, list) else [command]
        try:
            process = self.container.exec(
                command=command,
                environment=env,
                working_dir=working_dir,
                combine_stderr=True,
            )
            output, _ = process.wait_output()
            return output
        except pebble.ExecError as e:
            if should_log:
                logger.debug(e)
            raise e

    @override
    @retry(
        wait=wait_fixed(1),
        stop=stop_after_attempt(5),
        retry=retry_if_result(lambda result: result is False),
        retry_error_callback=lambda _: False,
    )
    def active(self) -> bool:
        if not self.installed:
            return False

        if self.service not in self.container.get_services():
            return False

        return self.container.get_service(self.service).is_running()

    @override
    def run_bin_command(
        self, bin_keyword: str, bin_args: list[str], opts: list[str] | None = None
    ) -> str:
        if opts is None:
            opts = []

        parsed_opts = {}
        for opt in opts:
            k, v = opt.split("=", maxsplit=1)
            parsed_opts[k] = v.replace("'", "")

        # TODO
        command = f"/opt/kafka/bin/kafka-{bin_keyword}.sh {' '.join(bin_args)}"
        return self.exec(command=command.split(), env=parsed_opts or None)

    @override
    def mkdir(self, path: str):
        try:
            self.exec(["mkdir", path])
        except pebble.ExecError as e:
            if "File exists" in str(e):
                return
            raise e

    @override
    def rmdir(self, path: str):
        self.exec(["rm", "-r", path])

    @override
    def remove(self, path: str, glob: bool = False):
        if not glob:
            self.exec(["rm", path])
            return

        dirname = os.path.dirname(path)
        for file in self.container.list_files(dirname):
            if fnmatch.fnmatch(file.path, path):
                self.exec(["rm", "-rf", file.path])

    @override
    def check_socket(self, host: str, port: int) -> bool:
        """Checks whether an IPv4 socket is healthy or not."""
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            return sock.connect_ex((host, port)) == 0

    @override
    def set_environment(self, env_vars: Iterable[str]) -> None:
        raw_current_env = self.read(self.paths.env)
        current_env = self.map_env(raw_current_env)

        updated_env = current_env | self.map_env(env_vars)
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
        self.write(content=content + "\n", path=self.paths.env)

    @property
    @override
    def installed(self) -> bool:
        """Whether the workload service is installed or not."""
        if not self.container.can_connect():
            return False

        return True

    @property
    @override
    def container_can_connect(self) -> bool:
        return self.container.can_connect()

    @property
    @override
    def layer(self) -> pebble.Layer:
        """Returns a Pebble configuration layer for Kafka Connect."""
        extra_opts = [
            f"-javaagent:{self.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.paths.jmx_prometheus_config}",
            f"-Djava.security.auth.login.config={self.paths.jaas}",
        ]
        command = f"/opt/kafka/bin/connect-distributed.sh {self.paths.worker_properties}"

        layer_config: pebble.LayerDict = {
            "summary": "Kafka Connect Layer",
            "description": "Pebble config layer for Apache Kafka Connect distributed worker",
            "services": {
                self.service: {
                    "override": "merge",
                    "summary": "Kafka Connect Worker",
                    "command": command,
                    "startup": "enabled",
                    "user": USER,
                    "group": GROUP,
                    "environment": {
                        "KAFKA_OPTS": " ".join(extra_opts),
                        "JAVA_HOME": "/usr/lib/jvm/java-18-openjdk-amd64",
                        "LOG_DIR": self.paths.logs_dir,
                    },
                }
            },
        }
        return pebble.Layer(layer_config)

    @staticmethod
    def map_env(env: Iterable[str]) -> dict[str, str]:
        """Parse env variables into a dict."""
        map_env = {}
        for var in env:
            key = "".join(var.split("=", maxsplit=1)[0])
            value = "".join(var.split("=", maxsplit=1)[1:])
            if key:
                # only check for keys, as we can have an empty value for a variable
                map_env[key] = value
        return map_env
