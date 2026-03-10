from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BrokerRuntimeStatus:
    provider: str
    state: str
    healthy: bool
    degraded_reason: str | None = None
    checked_at: str = _utcnow_iso()


class BrokerRuntimeBoundary(Protocol):
    async def ensure_running(self) -> BrokerRuntimeStatus: ...

    async def stop(self) -> BrokerRuntimeStatus: ...

    async def health_check(self) -> BrokerRuntimeStatus: ...

    async def reload(self) -> BrokerRuntimeStatus: ...

    async def controlled_restart(self) -> BrokerRuntimeStatus: ...

    async def get_status(self) -> BrokerRuntimeStatus: ...


class InMemoryBrokerRuntimeBoundary:
    def __init__(self, provider: str = "embedded_mosquitto") -> None:
        self._provider = provider
        self._state = "stopped"
        self._healthy = False
        self._degraded_reason: str | None = "runtime_not_started"

    async def ensure_running(self) -> BrokerRuntimeStatus:
        self._state = "running"
        self._healthy = True
        self._degraded_reason = None
        return self._status()

    async def stop(self) -> BrokerRuntimeStatus:
        self._state = "stopped"
        self._healthy = False
        self._degraded_reason = "runtime_stopped"
        return self._status()

    async def health_check(self) -> BrokerRuntimeStatus:
        return self._status()

    async def reload(self) -> BrokerRuntimeStatus:
        if self._state != "running":
            self._healthy = False
            self._degraded_reason = "runtime_not_running"
            return self._status()
        self._healthy = True
        self._degraded_reason = None
        return self._status()

    async def controlled_restart(self) -> BrokerRuntimeStatus:
        self._state = "running"
        self._healthy = True
        self._degraded_reason = None
        return self._status()

    async def get_status(self) -> BrokerRuntimeStatus:
        return self._status()

    def _status(self) -> BrokerRuntimeStatus:
        return BrokerRuntimeStatus(
            provider=self._provider,
            state=self._state,
            healthy=self._healthy,
            degraded_reason=self._degraded_reason,
            checked_at=_utcnow_iso(),
        )


class DockerMosquittoRuntimeBoundary:
    def __init__(
        self,
        *,
        live_dir: str,
        data_dir: str,
        log_dir: str,
        config_filename: str = "broker.conf",
        staged_dir: str | None = None,
        container_name: str = "synthia-mqtt-broker",
        image: str = "eclipse-mosquitto:2",
        host: str = "127.0.0.1",
        port: int = 1883,
    ) -> None:
        self._provider = "embedded_mosquitto_docker"
        self._live_dir = os.path.abspath(live_dir)
        if staged_dir is None:
            staged_dir = os.path.join(os.path.dirname(self._live_dir), "staged")
        self._staged_dir = os.path.abspath(staged_dir)
        self._data_dir = os.path.abspath(data_dir)
        self._log_dir = os.path.abspath(log_dir)
        self._config_filename = config_filename
        self._container_name = str(container_name).strip() or "synthia-mqtt-broker"
        self._image = str(image).strip() or "eclipse-mosquitto:2"
        self._host = str(host).strip() or "127.0.0.1"
        self._port = int(port)
        self._state = "stopped"
        self._healthy = False
        self._degraded_reason: str | None = "runtime_not_started"

    async def ensure_running(self) -> BrokerRuntimeStatus:
        return await asyncio.to_thread(self._ensure_running_sync)

    async def stop(self) -> BrokerRuntimeStatus:
        return await asyncio.to_thread(self._stop_sync)

    async def health_check(self) -> BrokerRuntimeStatus:
        return await asyncio.to_thread(self._health_check_sync)

    async def reload(self) -> BrokerRuntimeStatus:
        return await asyncio.to_thread(self._reload_sync)

    async def controlled_restart(self) -> BrokerRuntimeStatus:
        return await asyncio.to_thread(self._controlled_restart_sync)

    async def get_status(self) -> BrokerRuntimeStatus:
        return self._status()

    def _ensure_running_sync(self) -> BrokerRuntimeStatus:
        if not self._docker_available():
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = "docker_binary_not_found"
            return self._status()
        status = self._health_check_sync()
        if status.healthy:
            return status
        if self._container_exists_sync() and not self._container_running_sync():
            self._remove_container_sync()
        return self._start_sync()

    def _stop_sync(self) -> BrokerRuntimeStatus:
        if not self._docker_available():
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = "docker_binary_not_found"
            return self._status()
        self._remove_container_sync()
        self._state = "stopped"
        self._healthy = False
        self._degraded_reason = "runtime_stopped"
        return self._status()

    def _reload_sync(self) -> BrokerRuntimeStatus:
        if not self._docker_available():
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = "docker_binary_not_found"
            return self._status()
        if not self._container_running_sync():
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = "runtime_not_running"
            return self._status()
        cmd = self._docker_cmd(["kill", "--signal", "HUP", self._container_name])
        if cmd.returncode != 0:
            self._healthy = False
            self._degraded_reason = "reload_signal_failed"
            return self._status()
        return self._health_check_sync()

    def _controlled_restart_sync(self) -> BrokerRuntimeStatus:
        self._stop_sync()
        return self._start_sync()

    def _health_check_sync(self) -> BrokerRuntimeStatus:
        if not self._docker_available():
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = "docker_binary_not_found"
            return self._status()
        if not self._container_exists_sync():
            self._state = "stopped"
            self._healthy = False
            if self._degraded_reason in {None, "runtime_stopped"}:
                self._degraded_reason = "runtime_not_started"
            return self._status()
        if not self._container_running_sync():
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = "container_not_running"
            return self._status()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect((self._host, self._port))
        except Exception:
            self._state = "running"
            self._healthy = False
            self._degraded_reason = "broker_unreachable"
            return self._status()
        finally:
            sock.close()
        self._state = "running"
        self._healthy = True
        self._degraded_reason = None
        return self._status()

    def _start_sync(self) -> BrokerRuntimeStatus:
        conf_path = os.path.join(self._live_dir, self._config_filename)
        missing = self._missing_runtime_artifacts()
        if missing:
            staged_conf = os.path.join(self._staged_dir, self._config_filename)
            staged_exists = os.path.isfile(staged_conf) and os.path.getsize(staged_conf) > 0
            live_exists = os.path.isdir(self._live_dir)
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = (
                f"config_missing:expected={conf_path};"
                f"staged_exists={str(bool(staged_exists)).lower()};"
                f"live_dir_exists={str(bool(live_exists)).lower()};"
                f"missing={','.join(missing)};"
                "suggestion=run_setup_apply_or_runtime_rebuild"
            )
            return self._status()
        if not self._docker_available():
            self._state = "stopped"
            self._healthy = False
            self._degraded_reason = "docker_binary_not_found"
            return self._status()
        os.makedirs(self._live_dir, exist_ok=True)
        os.makedirs(self._data_dir, exist_ok=True)
        os.makedirs(self._log_dir, exist_ok=True)
        os.chmod(self._data_dir, 0o777)
        os.chmod(self._log_dir, 0o777)
        if self._container_exists_sync() and not self._container_running_sync():
            self._remove_container_sync()
        if not self._container_exists_sync():
            run = self._docker_cmd(
                [
                    "run",
                    "-d",
                    "--name",
                    self._container_name,
                    "--restart",
                    "unless-stopped",
                    "--network",
                    "host",
                    "-v",
                    f"{self._live_dir}:{self._live_dir}:ro",
                    "-v",
                    f"{self._data_dir}:{self._data_dir}",
                    "-v",
                    f"{self._log_dir}:{self._log_dir}",
                    self._image,
                    "mosquitto",
                    "-c",
                    conf_path,
                ]
            )
            if run.returncode != 0:
                self._state = "stopped"
                self._healthy = False
                self._degraded_reason = "runtime_start_failed"
                return self._status()
        else:
            start = self._docker_cmd(["start", self._container_name])
            if start.returncode != 0:
                self._state = "stopped"
                self._healthy = False
                self._degraded_reason = "runtime_start_failed"
                return self._status()
        return self._health_check_sync()

    def _missing_runtime_artifacts(self) -> list[str]:
        required = [
            os.path.join(self._live_dir, self._config_filename),
            os.path.join(self._live_dir, "acl_compiled.conf"),
            os.path.join(self._live_dir, "passwords.conf"),
        ]
        missing: list[str] = []
        for path in required:
            if not os.path.exists(path):
                missing.append(path)
                continue
            if not os.path.isfile(path):
                missing.append(path)
                continue
            if os.path.getsize(path) <= 0:
                missing.append(path)
        return missing

    def _docker_available(self) -> bool:
        return bool(shutil.which("docker"))

    def _docker_cmd(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def _container_exists_sync(self) -> bool:
        result = self._docker_cmd(
            ["ps", "-a", "--filter", f"name=^/{self._container_name}$", "--format", "{{.Names}}"]
        )
        if result.returncode != 0:
            return False
        return self._container_name in (result.stdout or "").splitlines()

    def _container_running_sync(self) -> bool:
        result = self._docker_cmd(
            ["ps", "--filter", f"name=^/{self._container_name}$", "--filter", "status=running", "--format", "{{.Names}}"]
        )
        if result.returncode != 0:
            return False
        return self._container_name in (result.stdout or "").splitlines()

    def _remove_container_sync(self) -> None:
        if not self._container_exists_sync():
            return
        self._docker_cmd(["rm", "-f", self._container_name])

    def _status(self) -> BrokerRuntimeStatus:
        return BrokerRuntimeStatus(
            provider=self._provider,
            state=self._state,
            healthy=self._healthy,
            degraded_reason=self._degraded_reason,
            checked_at=_utcnow_iso(),
        )


# Backward-compatible alias (legacy class name retained in imports).
MosquittoProcessRuntimeBoundary = DockerMosquittoRuntimeBoundary
