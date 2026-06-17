#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


DEFAULT_BASE_URL = "http://127.0.0.1:8787/api/v1"
CONNECTED_HDC_STATES = {"connected", "online", "ready"}
EMPTY_HDC_TARGET_MARKERS = {"", "[empty]", "empty", "none", "null"}


class ApiError(RuntimeError):
    def __init__(self, status: int, reason: str, body: str):
        super().__init__(f"HTTP {status} {reason}: {body}")
        self.status = status
        self.reason = reason
        self.body = body


class OhAutoClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout_sec: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.parsed = urlparse(self.base_url)
        if self.parsed.scheme not in {"http", "https"}:
            raise ValueError(f"Unsupported URL scheme: {self.parsed.scheme}")
        if not self.parsed.netloc:
            raise ValueError(f"Base URL must include host: {base_url}")

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_sec: float | None = None,
    ) -> Any:
        body = None
        headers = self._headers()
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"

        conn = self._connection(timeout_sec)
        try:
            conn.request(method, self._url_path(path), body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
        finally:
            conn.close()

        text = raw.decode("utf-8", errors="replace")
        if response.status >= 400:
            raise ApiError(response.status, response.reason, text)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def upload(self, file_path: Path, field_name: str = "file") -> Any:
        file_path = file_path.expanduser().resolve()
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(file_path)

        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        try:
            import requests  # type: ignore[import-untyped]
        except ImportError:
            requests = None

        if requests is not None:
            with file_path.open("rb") as handle:
                response = requests.post(
                    f"{self.base_url}/artifacts",
                    files={field_name: (file_path.name, handle, content_type)},
                    headers=self._headers(),
                    timeout=self.timeout_sec,
                )
            text = response.text
            if response.status_code >= 400:
                raise ApiError(response.status_code, response.reason, text)
            return response.json()

        boundary = f"oh_auto_{uuid.uuid4().hex}"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
        content_length = len(prefix) + file_path.stat().st_size + len(suffix)

        conn = self._connection(None)
        try:
            conn.putrequest("POST", self._url_path("/artifacts"))
            for key, value in self._headers().items():
                conn.putheader(key, value)
            conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            conn.putheader("Content-Length", str(content_length))
            conn.endheaders()
            conn.send(prefix)
            with file_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    conn.send(chunk)
            conn.send(suffix)
            response = conn.getresponse()
            raw = response.read()
        finally:
            conn.close()

        text = raw.decode("utf-8", errors="replace")
        if response.status >= 400:
            raise ApiError(response.status, response.reason, text)
        return json.loads(text)

    def download(self, artifact_id: str, out_path: Path) -> Any:
        out_path = out_path.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = out_path.with_name(f".{out_path.name}.tmp-{uuid.uuid4().hex}")
        digest = hashlib.sha256()
        size = 0
        conn = self._connection(None)
        try:
            conn.request(
                "GET",
                self._url_path(f"/artifacts/{artifact_id}/content"),
                headers=self._headers(),
            )
            response = conn.getresponse()
            if response.status >= 400:
                body = response.read().decode("utf-8", errors="replace")
                raise ApiError(response.status, response.reason, body)
            remote_sha256 = response.getheader("X-Artifact-Sha256")
            with temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)
        finally:
            conn.close()
        temp_path.replace(out_path)
        local_sha256 = digest.hexdigest()
        return {
            "artifact_id": artifact_id,
            "out_path": str(out_path),
            "size": size,
            "sha256": local_sha256,
            "remote_sha256": remote_sha256,
            "sha256_match": remote_sha256 in {None, local_sha256},
        }

    def stream_events(self, job_id: str) -> None:
        conn = self._connection(None)
        try:
            conn.request("GET", self._url_path(f"/jobs/{job_id}/events"), headers=self._headers())
            response = conn.getresponse()
            if response.status >= 400:
                raise ApiError(
                    response.status,
                    response.reason,
                    response.read().decode("utf-8", errors="replace"),
                )
            while True:
                line = response.readline()
                if not line:
                    break
                sys.stdout.write(line.decode("utf-8", errors="replace"))
                sys.stdout.flush()
        finally:
            conn.close()

    def _connection(self, timeout_sec: float | None):
        timeout = self.timeout_sec if timeout_sec is None else timeout_sec
        cls = HTTPSConnection if self.parsed.scheme == "https" else HTTPConnection
        return cls(self.parsed.netloc, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"X-API-Key": self.api_key}
        return {}

    def _url_path(self, path: str) -> str:
        base_path = self.parsed.path.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        if self.parsed.query:
            return f"{base_path}{suffix}?{self.parsed.query}"
        return f"{base_path}{suffix}"


def command_health(client: OhAutoClient, _args: argparse.Namespace) -> Any:
    return client.request_json("GET", "/health")


def command_version(client: OhAutoClient, _args: argparse.Namespace) -> Any:
    return client.request_json("GET", "/version")


def command_capabilities(client: OhAutoClient, _args: argparse.Namespace) -> Any:
    return client.request_json("GET", "/capabilities")


def command_profiles(client: OhAutoClient, _args: argparse.Namespace) -> Any:
    return client.request_json("GET", "/profiles")


def command_profile(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json("GET", f"/profiles/{quote(args.profile_id, safe='')}")


def command_admin_status(client: OhAutoClient, _args: argparse.Namespace) -> Any:
    return client.request_json("GET", "/admin/status")


def command_admin_list_files(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json("GET", f"/admin/files?path={quote(args.path)}")


def command_admin_read_file(client: OhAutoClient, args: argparse.Namespace) -> Any:
    result = client.request_json(
        "GET",
        f"/admin/files/content?path={quote(args.path)}&encoding={quote(args.encoding)}",
    )
    if args.out:
        Path(args.out).expanduser().write_text(result["content"], encoding=args.encoding)
        return {
            "path": result["path"],
            "out": args.out,
            "encoding": args.encoding,
            "size": result["size"],
        }
    if args.content_only:
        print(result["content"], end="")
        return None
    return result


def command_admin_write_file(client: OhAutoClient, args: argparse.Namespace) -> Any:
    content = Path(args.from_file).expanduser().read_text(encoding=args.encoding)
    return client.request_json(
        "PUT",
        "/admin/files/content",
        {
            "path": args.path,
            "content": content,
            "encoding": args.encoding,
            "create_parent": not args.no_create_parent,
        },
    )


def command_admin_shell(client: OhAutoClient, args: argparse.Namespace) -> Any:
    command = args.command if len(args.command) != 1 else args.command[0]
    if isinstance(command, list):
        command = " ".join(command)
    payload: dict[str, Any] = {
        "command": command,
        "timeout_sec": args.command_timeout_sec,
    }
    if args.cwd:
        payload["cwd"] = args.cwd
    return client.request_json(
        "POST",
        "/admin/shell",
        payload,
        timeout_sec=args.command_timeout_sec + 5,
    )


def command_admin_run_check(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json(
        "POST",
        "/admin/checks/run",
        {"check": args.check, "timeout_sec": args.command_timeout_sec},
        timeout_sec=args.command_timeout_sec + 5,
    )


def command_admin_restart(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json(
        "POST",
        "/admin/restart",
        {"delay_sec": args.delay_sec},
    )


def command_status(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json("GET", f"/devices/{args.device_id}/status")


def command_connect(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return connect_if_requested(client, args, force=True)


def command_wait_connected(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return wait_for_connected_hdc(
        client,
        args.device_id,
        timeout_sec=args.timeout_sec,
        interval_sec=args.interval_sec,
        channel=args.connect_channel,
        target=args.connect_target,
        baudrate=args.connect_baudrate,
        retry_connect=args.connect_retry,
    )


def command_preflight(client: OhAutoClient, args: argparse.Namespace) -> Any:
    health = client.request_json("GET", "/health")
    capabilities = client.request_json("GET", "/capabilities")
    status = client.request_json("GET", f"/devices/{args.device_id}/status")
    templates = {
        item.get("template_id"): item
        for item in capabilities.get("flash_templates", [])
        if isinstance(item, dict)
    }
    connected_targets = connected_hdc_targets(status)
    template = templates.get(args.template_id, {})
    step_types = set(template.get("step_types") or [])
    titan_flash_template = {"wait_titan_fastboot", "titan_flash"}.issubset(step_types)
    wait_titan_api_available = bool(
        capabilities.get("operations", {}).get("wait_titan_fastboot")
    )
    running_jobs = status.get("running_jobs", [])
    checks = {
        "health_ok": health.get("status") == "ok",
        "device_exists": any(
            item.get("device_id") == args.device_id for item in capabilities.get("devices", [])
        ),
        "template_available": template.get("valid") is True,
        "device_connected": bool(connected_targets),
        "device_unlocked": not status.get("device_locked", False),
        "no_running_jobs": not running_jobs,
        "template_can_wait_titan_fastboot": titan_flash_template,
    }
    host_ready = all(
        checks[key]
        for key in [
            "health_ok",
            "device_exists",
            "template_available",
            "device_unlocked",
            "no_running_jobs",
        ]
    )
    hdc_preflight_ok = host_ready and checks["device_connected"]
    flash_job_submittable = host_ready and (checks["device_connected"] or titan_flash_template)
    notes = []
    if titan_flash_template:
        if wait_titan_api_available:
            notes.append(
                "Preflight does not change device state; after reboot fastboot, run wait-titan-fastboot for direct Titan burn-mode evidence."
            )
        else:
            notes.append(
                "Titan burn mode is not directly probed by preflight; it is checked inside the flash job."
            )
    if not checks["device_connected"] and titan_flash_template:
        notes.append(
            "HDC Offline can be normal in Titan burn mode and does not by itself prove the board is absent."
        )
    return {
        "ok": flash_job_submittable,
        "preflight_mode": "flash_job_submission",
        "checks": checks,
        "hdc_preflight_ok": hdc_preflight_ok,
        "flash_job_submittable": flash_job_submittable,
        "titan_burn_mode_confirmed": None,
        "burn_mode_probe": {
            "available": wait_titan_api_available,
            "command": (
                f"oh_autoctl.py wait-titan-fastboot --template-id {args.template_id} --timeout-sec 30"
                if wait_titan_api_available
                else None
            ),
            "reason": None
            if wait_titan_api_available
            else "oh-auto exposes wait_titan_fastboot only as part of a flash job",
        },
        "health": health,
        "template_id": args.template_id,
        "connected_targets": connected_targets,
        "running_jobs": running_jobs,
        "notes": notes,
    }


def command_diagnose_jobs(client: OhAutoClient, args: argparse.Namespace) -> Any:
    status = client.request_json("GET", f"/devices/{args.device_id}/status")
    capabilities: dict[str, Any] = {}
    capabilities_error = None
    try:
        capabilities = client.request_json("GET", "/capabilities")
    except Exception as exc:
        capabilities_error = f"{type(exc).__name__}: {exc}"
    data_dir = capabilities.get("runtime", {}).get("data_dir") or "F:\\oh-auto-data"
    running_jobs = status.get("running_jobs", [])
    diagnostics: list[dict[str, Any]] = []
    storage_full_detected = False

    for item in running_jobs:
        job_id = item.get("job_id")
        if not job_id:
            continue
        detail: dict[str, Any] = {"status_entry": item}
        try:
            detail["job"] = client.request_json("GET", f"/jobs/{job_id}")
        except ApiError as exc:
            detail["job_error"] = str(exc)
        try:
            events = client.request_json("GET", f"/jobs/{job_id}/logs?stream=events&offset=0")
            content = events.get("content", "") if isinstance(events, dict) else str(events)
            detail["events_tail"] = content[-args.tail_chars:]
            if "database or disk is full" in content or "OperationalError" in content:
                detail["storage_full_evidence"] = True
                storage_full_detected = True
        except ApiError as exc:
            detail["events_error"] = str(exc)
        diagnostics.append(detail)

    recommendations: list[str] = []
    if storage_full_detected:
        recommendations.extend([
            "Stop submitting device jobs; stale running/queued jobs may be DB state, not live processes.",
            f"Free space under {data_dir}, especially old artifacts and runs.",
            "Restart the oh-auto service, then rerun status and preflight.",
            "Require no running_jobs and preflight ok=true before flashing.",
        ])
    elif running_jobs:
        recommendations.append(
            "Running jobs exist but no storage-full evidence was found in event tails; inspect logs or cancel only after preserving needed output."
        )
    else:
        recommendations.append("No running_jobs reported by status.")

    return {
        "ok": not running_jobs,
        "device_id": args.device_id,
        "running_job_count": len(running_jobs),
        "storage_full_detected": storage_full_detected,
        "runtime_data_dir": data_dir,
        "capabilities_error": capabilities_error,
        "diagnostics": diagnostics,
        "recommendations": recommendations,
    }


def command_upload(client: OhAutoClient, args: argparse.Namespace) -> Any:
    result = client.upload(Path(args.file))
    if args.id_only:
        print(result["artifact_id"])
        return None
    return result


def command_download_artifact(client: OhAutoClient, args: argparse.Namespace) -> Any:
    result = client.download(args.artifact_id, Path(args.out))
    if not result["sha256_match"]:
        raise RuntimeError(
            f"Downloaded sha256 mismatch: local={result['sha256']} remote={result['remote_sha256']}"
        )
    return result


def command_promote_artifact(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json(
        "POST",
        f"/artifacts/{args.artifact_id}/promote",
        {"dest_path": args.dest, "overwrite": not args.no_overwrite},
        timeout_sec=args.timeout_sec,
    )


def command_push(client: OhAutoClient, args: argparse.Namespace) -> Any:
    connect_if_requested(client, args)
    payload: dict[str, Any] = {
        "remote_path": args.remote_path,
        "options": args.option,
        "timeout_sec": args.command_timeout_sec,
    }
    if args.artifact_id:
        payload["artifact_id"] = args.artifact_id
    if args.local_path:
        payload["local_path"] = args.local_path
    if not args.artifact_id and not args.local_path:
        raise ValueError("push requires --artifact-id or --local-path")
    job = client.request_json("POST", f"/devices/{args.device_id}/ops/push", payload)
    return wait_if_requested(client, job, args)


def command_pull(client: OhAutoClient, args: argparse.Namespace) -> Any:
    connect_if_requested(client, args)
    payload: dict[str, Any] = {
        "remote_path": args.remote_path,
        "options": args.option,
        "timeout_sec": args.command_timeout_sec,
    }
    if args.local_path:
        payload["local_path"] = args.local_path
    if args.filename:
        payload["filename"] = args.filename
    job = client.request_json("POST", f"/devices/{args.device_id}/ops/pull", payload)
    return wait_if_requested(client, job, args)


def command_reboot(client: OhAutoClient, args: argparse.Namespace) -> Any:
    connect_if_requested(client, args)
    if args.mode == "fastboot":
        job = client.request_json(
            "POST",
            f"/devices/{args.device_id}/ops/shell",
            {"command": "reboot fastboot", "timeout_sec": args.command_timeout_sec},
        )
        if not args.wait:
            return job
        return wait_shell_and_collect(client, job, args)
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/ops/reboot",
        {"mode": args.mode, "timeout_sec": args.command_timeout_sec},
    )
    return wait_if_requested(client, job, args)


def command_bugreport(client: OhAutoClient, args: argparse.Namespace) -> Any:
    connect_if_requested(client, args)
    payload: dict[str, Any] = {
        "filename": args.filename,
        "timeout_sec": args.command_timeout_sec,
    }
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/ops/bugreport",
        payload,
    )
    return wait_if_requested(client, job, args)


def command_shell(client: OhAutoClient, args: argparse.Namespace) -> Any:
    connect_if_requested(client, args)
    command = args.command if len(args.command) != 1 else args.command[0]
    if isinstance(command, list):
        command = " ".join(command)
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/ops/shell",
        {"command": command, "timeout_sec": args.command_timeout_sec},
    )
    if not args.wait:
        return job
    return wait_shell_and_collect(client, job, args)


def command_wifi_smoke(client: OhAutoClient, args: argparse.Namespace) -> Any:
    connect_if_requested(client, args)
    payload: dict[str, Any] = {
        "ssid": args.ssid,
        "psk": args.psk,
        "diag_path": args.diag_path,
        "connect_timeout_sec": args.connect_timeout_sec,
        "command_timeout_sec": args.command_timeout_sec,
        "gateway_ping_count": args.gateway_ping_count,
        "gateway_ping_timeout_sec": args.gateway_ping_timeout_sec,
        "external_ping_count": args.external_ping_count,
        "external_ping_timeout_sec": args.external_ping_timeout_sec,
    }
    if args.external_host:
        payload["external_host"] = args.external_host
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/ops/wifi-smoke",
        payload,
    )
    return wait_if_requested(client, job, args)


def command_serial(client: OhAutoClient, args: argparse.Namespace) -> Any:
    command = args.command if len(args.command) != 1 else args.command[0]
    if isinstance(command, list):
        command = " ".join(command)
    payload: dict[str, Any] = {
        "command": command,
        "newline": args.newline,
        "read_timeout_sec": args.read_timeout_sec,
        "idle_timeout_sec": args.idle_timeout_sec,
        "write_timeout_sec": args.write_timeout_sec,
        "encoding": args.encoding,
    }
    if args.port:
        payload["port"] = args.port
    if args.baudrate:
        payload["baudrate"] = args.baudrate
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/ops/serial",
        payload,
    )
    return wait_if_requested(client, job, args)


def command_serial_log(client: OhAutoClient, args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {
        "timeout_sec": args.capture_timeout_sec,
        "idle_timeout_sec": args.idle_timeout_sec,
        "max_bytes": args.max_bytes,
        "timestamp_lines": not args.no_timestamp,
        "encoding": args.encoding,
    }
    if args.port:
        payload["port"] = args.port
    if args.baudrate:
        payload["baudrate"] = args.baudrate
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/logs/serial/start",
        payload,
    )
    return wait_if_requested(client, job, args)


def command_hilog(client: OhAutoClient, args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {
        "args": args.arg,
        "timeout_sec": args.capture_timeout_sec,
    }
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/logs/hilog/start",
        payload,
    )
    return wait_if_requested(client, job, args)


def command_flash(client: OhAutoClient, args: argparse.Namespace) -> Any:
    artifacts = parse_key_value_list(args.artifact)
    if args.image:
        artifacts["image"] = args.image
    if not artifacts:
        raise ValueError("flash requires --image or at least one --artifact name=value")
    params = parse_key_value_list(args.param)
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/flash",
        {"template_id": args.template_id, "artifacts": artifacts, "params": params},
    )
    return wait_if_requested(client, job, args)


def command_wait_titan_fastboot(client: OhAutoClient, args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {
        "template_id": args.template_id,
        "params": parse_key_value_list(args.param),
        "timeout_sec": args.timeout_sec,
    }
    if args.interval_sec is not None:
        payload["interval_sec"] = args.interval_sec
    if args.list_timeout_sec is not None:
        payload["list_timeout_sec"] = args.list_timeout_sec
    if args.serial:
        payload["serial"] = args.serial
    return client.request_json(
        "POST",
        f"/devices/{args.device_id}/wait_titan_fastboot",
        payload,
        timeout_sec=args.timeout_sec + 10,
    )


def command_wait(client: OhAutoClient, args: argparse.Namespace) -> Any:
    if args.events:
        client.stream_events(args.job_id)
    return client.request_json(
        "POST",
        f"/jobs/{args.job_id}/wait?timeout_sec={args.timeout_sec}",
        {},
        timeout_sec=args.timeout_sec + 5,
    )


def command_job(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json("GET", f"/jobs/{args.job_id}")


def command_logs(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json(
        "GET",
        f"/jobs/{args.job_id}/logs?stream={args.stream}&offset={args.offset}",
    )


def command_events(client: OhAutoClient, args: argparse.Namespace) -> Any:
    client.stream_events(args.job_id)
    return None


def command_cancel(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json("POST", f"/jobs/{args.job_id}/cancel", {})


def command_smoke(client: OhAutoClient, args: argparse.Namespace) -> Any:
    wait_connected_result = None
    if args.wait_connected:
        wait_connected_result = wait_for_connected_hdc(
            client,
            args.device_id,
            timeout_sec=args.wait_connected_timeout_sec,
            interval_sec=args.wait_connected_interval_sec,
            channel=args.connect_channel,
            target=args.connect_target,
            baudrate=args.connect_baudrate,
            retry_connect=args.connect_retry,
        )
        if not wait_connected_result["ok"]:
            return {
                "ok": False,
                "wait_connected": wait_connected_result,
                "connect": None,
                "results": [],
            }
    connect_result = connect_if_requested(client, args)
    commands = [
        ("echo oh_auto_agent_smoke_ok", "oh_auto_agent_smoke_ok"),
    ]
    if args.set_boot_escape_ack:
        commands.extend([
            (
                f"param set {args.boot_escape_ack_param} true",
                "",
            ),
            (f"param get {args.boot_escape_ack_param}", "true"),
        ])
    commands.extend([
        ("param get const.product.name", None),
        ("param get const.ohos.fullname", None),
        ("uname -a", "Linux"),
    ])
    results = []
    for command, expected in commands:
        job = client.request_json(
            "POST",
            f"/devices/{args.device_id}/ops/shell",
            {"command": command, "timeout_sec": args.command_timeout_sec},
        )
        shell_result = wait_shell_and_collect(client, job, args, expected=expected)
        results.append({
            "command": command,
            **shell_result,
        })
        if shell_result["job"].get("status") != "succeeded" or not shell_result["stdout_valid"]:
            break
    return {
        "ok": all(
            item["job"].get("status") == "succeeded" and item.get("stdout_valid") is True
            for item in results
        ),
        "wait_connected": wait_connected_result,
        "connect": connect_result,
        "results": results,
    }


def command_sync_time(client: OhAutoClient, args: argparse.Namespace) -> Any:
    wait_connected_result = None
    if args.wait_connected:
        wait_connected_result = wait_for_connected_hdc(
            client,
            args.device_id,
            timeout_sec=args.wait_connected_timeout_sec,
            interval_sec=args.wait_connected_interval_sec,
            channel=args.connect_channel,
            target=args.connect_target,
            baudrate=args.connect_baudrate,
            retry_connect=args.connect_retry,
        )
        if not wait_connected_result["ok"]:
            return {
                "ok": False,
                "epoch_sec": None,
                "host_utc": None,
                "wait_connected": wait_connected_result,
                "connect": None,
                "result": None,
            }
    connect_result = connect_if_requested(client, args)
    epoch_sec = args.epoch_sec if args.epoch_sec is not None else int(time.time())
    host_utc = datetime.fromtimestamp(epoch_sec, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    write_rtc = "" if args.no_hwclock else "hwclock -u -w;"
    command = (
        "echo BEFORE; date; hwclock -r 2>&1 || true; "
        "echo SET; "
        f"date -u -s @{epoch_sec}; {write_rtc} "
        "echo AFTER; date; hwclock -r 2>&1 || true; cat /proc/driver/rtc 2>/dev/null || true"
    )
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/ops/shell",
        {"command": command, "timeout_sec": args.command_timeout_sec},
    )
    result = wait_shell_and_collect(client, job, args)
    ok = result["job"].get("status") == "succeeded" and result.get("stdout_valid") is True
    return {
        "ok": ok,
        "epoch_sec": epoch_sec,
        "host_utc": host_utc,
        "write_rtc": not args.no_hwclock,
        "wait_connected": wait_connected_result,
        "connect": connect_result,
        "result": {
            "command": command,
            **result,
        },
    }


def normalized_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def hdc_targets(status: dict[str, Any]) -> list[dict[str, Any]]:
    targets = status.get("hdc", {}).get("targets", [])
    return [item for item in targets if isinstance(item, dict)]


def hdc_target_key(item: dict[str, Any]) -> str:
    for key in ["connect_key", "target", "serial", "device_id", "id"]:
        value = normalized_text(item.get(key))
        if value:
            return value
    return ""


def hdc_target_channel(item: dict[str, Any]) -> str:
    for key in ["transport", "channel", "type"]:
        value = normalized_text(item.get(key))
        if value:
            return value
    return ""


def hdc_target_values(item: dict[str, Any]) -> set[str]:
    values = set()
    for key in ["connect_key", "target", "serial", "device_id", "id"]:
        value = normalized_text(item.get(key))
        if value:
            values.add(value.lower())
    raw = normalized_text(item.get("raw"))
    if raw:
        values.add(raw.split()[0].lower())
    return values


def hdc_target_is_real(item: dict[str, Any]) -> bool:
    key = hdc_target_key(item).lower()
    raw = normalized_text(item.get("raw")).lower()
    return key not in EMPTY_HDC_TARGET_MARKERS and raw not in EMPTY_HDC_TARGET_MARKERS


def hdc_target_matches(item: dict[str, Any], channel: str | None = None, target: str | None = None) -> bool:
    if channel:
        actual_channel = hdc_target_channel(item)
        if actual_channel and actual_channel.lower() != channel.lower():
            return False
    if target and target.strip().lower() not in hdc_target_values(item):
        return False
    return True


def connected_hdc_targets(
    status: dict[str, Any],
    channel: str | None = None,
    target: str | None = None,
) -> list[dict[str, Any]]:
    matches = []
    for item in hdc_targets(status):
        state = normalized_text(item.get("status")).lower()
        if state not in CONNECTED_HDC_STATES:
            continue
        if not hdc_target_is_real(item):
            continue
        if not hdc_target_matches(item, channel=channel, target=target):
            continue
        matches.append(item)
    return matches


def wait_for_connected_hdc(
    client: OhAutoClient,
    device_id: str,
    timeout_sec: float,
    interval_sec: float,
    channel: str | None = None,
    target: str | None = None,
    baudrate: int | None = None,
    retry_connect: bool = False,
) -> dict[str, Any]:
    start = time.monotonic()
    deadline = start + max(timeout_sec, 0)
    interval = max(interval_sec, 0.2)
    attempts = 0
    last_status = None
    last_error = None
    last_connect = None
    last_connect_error = None

    while True:
        attempts += 1
        if retry_connect and (channel or target or baudrate):
            payload: dict[str, Any] = {"channel": channel or "usb"}
            if target:
                payload["target"] = target
            if baudrate:
                payload["baudrate"] = baudrate
            try:
                last_connect = client.request_json("POST", f"/devices/{device_id}/connect", payload)
                last_connect_error = None
            except Exception as exc:
                last_connect_error = f"{type(exc).__name__}: {exc}"
        try:
            last_status = client.request_json("GET", f"/devices/{device_id}/status")
            last_error = None
            matches = connected_hdc_targets(last_status, channel=channel, target=target)
            if matches:
                return {
                    "ok": True,
                    "elapsed_sec": round(time.monotonic() - start, 3),
                    "attempts": attempts,
                    "target": matches[0],
                    "matches": matches,
                    "connect": last_connect,
                    "last_status": last_status,
                }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        now = time.monotonic()
        if now >= deadline:
            break
        time.sleep(min(interval, max(deadline - now, 0)))

    return {
        "ok": False,
        "elapsed_sec": round(time.monotonic() - start, 3),
        "attempts": attempts,
        "requested": {
            "channel": channel,
            "target": target,
            "baudrate": baudrate,
        },
        "last_error": last_error,
        "last_connect": last_connect,
        "last_connect_error": last_connect_error,
        "last_targets": hdc_targets(last_status or {}),
        "last_status": last_status,
    }


def smoke_stdout_valid(stdout_text: str, expected: str | None) -> bool:
    failure_markers = [
        "[Fail]",
        "[Empty]",
        "ExecuteCommand need connect-key",
        "Offline",
        "No any connected target",
    ]
    if any(marker in stdout_text for marker in failure_markers):
        return False
    if expected == "":
        return True
    stripped = stdout_text.strip()
    if not stripped:
        return False
    if expected is not None and expected not in stdout_text:
        return False
    return True


def wait_shell_and_collect(
    client: OhAutoClient,
    job: dict[str, Any],
    args: argparse.Namespace,
    expected: str | None = None,
) -> dict[str, Any]:
    job_id = job["job_id"]
    if getattr(args, "events", False):
        client.stream_events(job_id)
    finished = client.request_json(
        "POST",
        f"/jobs/{job_id}/wait?timeout_sec={args.timeout_sec}",
        {},
        timeout_sec=args.timeout_sec + 5,
    )
    stdout = client.request_json("GET", f"/jobs/{job_id}/logs?stream=stdout&offset=0")
    stderr = client.request_json("GET", f"/jobs/{job_id}/logs?stream=stderr&offset=0")
    stdout_text = stdout.get("content", "")
    return {
        "job": finished,
        "stdout": stdout_text,
        "stderr": stderr.get("content", ""),
        "stdout_valid": smoke_stdout_valid(stdout_text, expected),
    }


def wait_if_requested(client: OhAutoClient, job: dict[str, Any], args: argparse.Namespace) -> Any:
    if not args.wait:
        return job
    job_id = job["job_id"]
    if args.events:
        client.stream_events(job_id)
    return client.request_json(
        "POST",
        f"/jobs/{job_id}/wait?timeout_sec={args.timeout_sec}",
        {},
        timeout_sec=args.timeout_sec + 5,
    )


def connect_if_requested(
    client: OhAutoClient,
    args: argparse.Namespace,
    force: bool = False,
) -> Any:
    channel = getattr(args, "connect_channel", None)
    target = getattr(args, "connect_target", None)
    baudrate = getattr(args, "connect_baudrate", None)
    if not force and not (channel or target or baudrate):
        return None
    payload: dict[str, Any] = {"channel": channel or "usb"}
    if target:
        payload["target"] = target
    if baudrate:
        payload["baudrate"] = baudrate
    return client.request_json(
        "POST",
        f"/devices/{args.device_id}/connect",
        payload,
    )


def parse_key_value_list(items: list[str] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"Expected name=value: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Empty key in: {item}")
        result[key] = parse_scalar(value)
    return result


def parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def print_json(value: Any) -> None:
    if value is not None:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI for OpenHarmony local automation service")
    parser.add_argument(
        "--base-url",
        default=os.getenv("OH_AUTO_BASE_URL", DEFAULT_BASE_URL),
        help="Service base URL, default: %(default)s",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OH_AUTO_API_KEY", ""),
        help="Optional API key or OH_AUTO_API_KEY when the service enables auth",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=float(os.getenv("OH_AUTO_TIMEOUT_SEC", "30")),
        help="HTTP timeout for normal requests",
    )
    parser.add_argument(
        "--device-id",
        default=os.getenv("OH_AUTO_DEVICE_ID", "default"),
        help="Logical device id",
    )
    default_profile_id = os.getenv("OH_AUTO_PROFILE_ID")
    default_template_id = os.getenv("OH_AUTO_FLASH_TEMPLATE_ID")
    default_wifi_diag_path = os.getenv("OH_AUTO_WIFI_DIAG_PATH")

    subparsers = parser.add_subparsers(dest="command_name", required=True)
    add_simple_command(subparsers, "health", command_health)
    add_simple_command(subparsers, "version", command_version)
    add_simple_command(subparsers, "capabilities", command_capabilities)
    add_simple_command(subparsers, "profiles", command_profiles)
    profile = add_simple_command(subparsers, "profile", command_profile)
    if default_profile_id:
        profile.add_argument("profile_id", nargs="?", default=default_profile_id)
    else:
        profile.add_argument("profile_id")
    add_simple_command(subparsers, "status", command_status)

    add_simple_command(subparsers, "admin-status", command_admin_status)

    admin_list = add_simple_command(subparsers, "admin-list-files", command_admin_list_files)
    admin_list.add_argument("path", nargs="?", default=".")

    admin_read = add_simple_command(subparsers, "admin-read-file", command_admin_read_file)
    admin_read.add_argument("path")
    admin_read.add_argument("--encoding", default="utf-8")
    admin_read.add_argument("--out")
    admin_read.add_argument("--content-only", action="store_true")

    admin_write = add_simple_command(subparsers, "admin-write-file", command_admin_write_file)
    admin_write.add_argument("path")
    admin_write.add_argument("--from-file", required=True)
    admin_write.add_argument("--encoding", default="utf-8")
    admin_write.add_argument("--no-create-parent", action="store_true")

    admin_shell = add_simple_command(subparsers, "admin-shell", command_admin_shell)
    admin_shell.add_argument("command", nargs="+")
    admin_shell.add_argument("--cwd")
    admin_shell.add_argument("--command-timeout-sec", type=float, default=300)

    admin_check = add_simple_command(subparsers, "admin-run-check", command_admin_run_check)
    admin_check.add_argument("check", choices=["py_compile", "pytest"], default="py_compile")
    admin_check.add_argument("--command-timeout-sec", type=float, default=300)

    admin_restart = add_simple_command(subparsers, "admin-restart", command_admin_restart)
    admin_restart.add_argument("--delay-sec", type=float, default=2)

    connect = add_simple_command(subparsers, "connect", command_connect)
    add_connect_arguments(connect, required_channel=True)

    wait_connected = add_simple_command(subparsers, "wait-connected", command_wait_connected)
    add_connect_arguments(wait_connected)
    wait_connected.add_argument("--timeout-sec", type=float, default=180)
    wait_connected.add_argument("--interval-sec", type=float, default=2)
    wait_connected.add_argument(
        "--connect-retry",
        action="store_true",
        help="Retry HDC target selection while polling status.",
    )

    preflight = add_simple_command(subparsers, "preflight", command_preflight)
    preflight.add_argument(
        "--template-id",
        default=default_template_id,
        required=default_template_id is None,
        help="Flash template id; may be provided by OH_AUTO_FLASH_TEMPLATE_ID.",
    )

    diagnose_jobs = add_simple_command(subparsers, "diagnose-jobs", command_diagnose_jobs)
    diagnose_jobs.add_argument(
        "--tail-chars",
        type=int,
        default=4000,
        help="Number of event-log tail characters to include for each running job.",
    )

    upload = add_simple_command(subparsers, "upload", command_upload)
    upload.add_argument("file")
    upload.add_argument("--id-only", action="store_true")

    download = add_simple_command(subparsers, "download-artifact", command_download_artifact)
    download.add_argument("artifact_id")
    download.add_argument("--out", required=True)

    promote = add_simple_command(subparsers, "promote-artifact", command_promote_artifact)
    promote.add_argument("artifact_id")
    promote.add_argument("--dest", required=True)
    promote.add_argument("--no-overwrite", action="store_true")

    push = add_job_command(subparsers, "push", command_push)
    add_connect_arguments(push)
    push.add_argument("remote_path", help="Device-side destination path.")
    push.add_argument("--artifact-id", help="Artifact id returned by upload.")
    push.add_argument("--local-path", help="Allowed Windows local source path.")
    push.add_argument("--option", action="append", default=[], help="Raw hdc file send option.")
    push.add_argument("--command-timeout-sec", type=float, default=300)

    pull = add_job_command(subparsers, "pull", command_pull)
    add_connect_arguments(pull)
    pull.add_argument("remote_path", help="Device-side source path.")
    pull.add_argument("--local-path", help="Allowed Windows local destination path.")
    pull.add_argument("--filename", help="Artifact filename when local_path is omitted.")
    pull.add_argument("--option", action="append", default=[], help="Raw hdc file recv option.")
    pull.add_argument("--command-timeout-sec", type=float, default=300)

    reboot = add_job_command(subparsers, "reboot", command_reboot)
    add_connect_arguments(reboot)
    reboot.add_argument(
        "--mode",
        choices=["normal", "bootloader", "recovery", "updater", "fastboot"],
        default="normal",
        help="Use fastboot to send the literal device shell command 'reboot fastboot'.",
    )
    reboot.add_argument("--command-timeout-sec", type=float, default=120)

    bugreport = add_job_command(subparsers, "bugreport", command_bugreport)
    add_connect_arguments(bugreport)
    bugreport.add_argument("--filename", help="Artifact filename for the collected report.")
    bugreport.add_argument("--command-timeout-sec", type=float, default=600)

    shell = add_job_command(subparsers, "shell", command_shell)
    add_connect_arguments(shell)
    shell.add_argument("command", nargs="+")
    shell.add_argument("--command-timeout-sec", type=float, default=300)

    wifi_smoke = add_job_command(subparsers, "wifi-smoke", command_wifi_smoke)
    add_connect_arguments(wifi_smoke)
    wifi_smoke.add_argument("--ssid", required=True)
    wifi_smoke.add_argument("--psk", required=True)
    wifi_smoke.add_argument(
        "--diag-path",
        default=default_wifi_diag_path,
        required=default_wifi_diag_path is None,
        help=(
            "Device-side WiFi diagnostic helper path. Pass the board-specific "
            "path or set OH_AUTO_WIFI_DIAG_PATH."
        ),
    )
    wifi_smoke.add_argument("--connect-timeout-sec", type=int, default=45)
    wifi_smoke.add_argument("--command-timeout-sec", type=float, default=90)
    wifi_smoke.add_argument("--gateway-ping-count", type=int, default=2)
    wifi_smoke.add_argument("--gateway-ping-timeout-sec", type=int, default=3)
    wifi_smoke.add_argument("--external-host")
    wifi_smoke.add_argument("--external-ping-count", type=int, default=2)
    wifi_smoke.add_argument("--external-ping-timeout-sec", type=int, default=3)

    serial = add_job_command(subparsers, "serial", command_serial)
    serial.add_argument("command", nargs="+")
    serial.add_argument("--port")
    serial.add_argument("--baudrate", type=int)
    serial.add_argument("--newline", choices=["crlf", "lf", "cr", "none"], default="crlf")
    serial.add_argument("--read-timeout-sec", type=float, default=5)
    serial.add_argument("--idle-timeout-sec", type=float, default=0.5)
    serial.add_argument("--write-timeout-sec", type=float, default=2)
    serial.add_argument("--encoding", default="utf-8")

    serial_log = add_job_command(subparsers, "serial-log", command_serial_log)
    serial_log.add_argument("--port")
    serial_log.add_argument("--baudrate", type=int)
    serial_log.add_argument(
        "--capture-timeout-sec",
        type=float,
        default=None,
        help="Service-side serial capture timeout; omit for service default.",
    )
    serial_log.add_argument("--idle-timeout-sec", type=float, default=None)
    serial_log.add_argument("--max-bytes", type=int, default=None)
    serial_log.add_argument("--no-timestamp", action="store_true")
    serial_log.add_argument("--encoding", default="utf-8")

    hilog = add_job_command(subparsers, "hilog", command_hilog)
    hilog.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Argument passed to hilog; repeat for multiple args.",
    )
    hilog.add_argument(
        "--capture-timeout-sec",
        type=float,
        default=None,
        help="Service-side hilog capture timeout; omit for service default.",
    )

    flash = add_job_command(subparsers, "flash", command_flash)
    flash.add_argument("template_id")
    flash.add_argument("--image", help="Artifact id or allowed Windows local path for artifacts.image")
    flash.add_argument("--artifact", action="append", default=[], help="Artifact mapping, name=value")
    flash.add_argument("--param", action="append", default=[], help="Template parameter, name=value")

    wait_titan = add_simple_command(
        subparsers, "wait-titan-fastboot", command_wait_titan_fastboot
    )
    wait_titan.add_argument(
        "--template-id",
        default=default_template_id,
        required=default_template_id is None,
        help="Flash template id; may be provided by OH_AUTO_FLASH_TEMPLATE_ID.",
    )
    wait_titan.add_argument("--timeout-sec", type=float, default=30)
    wait_titan.add_argument("--interval-sec", type=float, default=None)
    wait_titan.add_argument("--list-timeout-sec", type=float, default=None)
    wait_titan.add_argument("--serial")
    wait_titan.add_argument("--param", action="append", default=[], help="Template parameter, name=value")

    wait = add_simple_command(subparsers, "wait", command_wait)
    wait.add_argument("job_id")
    wait.add_argument("--timeout-sec", type=float, default=600)
    wait.add_argument("--events", action="store_true")

    job = add_simple_command(subparsers, "job", command_job)
    job.add_argument("job_id")

    logs = add_simple_command(subparsers, "logs", command_logs)
    logs.add_argument("job_id")
    logs.add_argument("--stream", choices=["stdout", "stderr", "events"], default="stdout")
    logs.add_argument("--offset", type=int, default=0)

    events = add_simple_command(subparsers, "events", command_events)
    events.add_argument("job_id")

    cancel = add_simple_command(subparsers, "cancel", command_cancel)
    cancel.add_argument("job_id")

    smoke = add_simple_command(subparsers, "smoke", command_smoke)
    add_connect_arguments(smoke)
    smoke.add_argument("--timeout-sec", type=float, default=60)
    smoke.add_argument("--command-timeout-sec", type=float, default=60)
    smoke.add_argument(
        "--wait-connected",
        action="store_true",
        help="Wait for a real Connected/Online/Ready HDC target before smoke commands.",
    )
    smoke.add_argument("--wait-connected-timeout-sec", type=float, default=180)
    smoke.add_argument("--wait-connected-interval-sec", type=float, default=2)
    smoke.add_argument(
        "--connect-retry",
        action="store_true",
        help="Retry HDC target selection while --wait-connected polls status.",
    )
    smoke.add_argument(
        "--set-boot-escape-ack",
        action="store_true",
        help="Set the configured boot escape acknowledgement as soon as smoke starts.",
    )
    smoke.add_argument(
        "--boot-escape-ack-param",
        default="startup.porting.boot_escape.ack",
        help="Parameter written by --set-boot-escape-ack.",
    )

    sync_time = add_simple_command(subparsers, "sync-time", command_sync_time)
    add_connect_arguments(sync_time)
    sync_time.add_argument(
        "--wait-connected",
        action="store_true",
        help="Wait for a real Connected/Online/Ready HDC target before setting time.",
    )
    sync_time.add_argument("--wait-connected-timeout-sec", type=float, default=180)
    sync_time.add_argument("--wait-connected-interval-sec", type=float, default=2)
    sync_time.add_argument(
        "--connect-retry",
        action="store_true",
        help="Retry HDC target selection while --wait-connected polls status.",
    )
    sync_time.add_argument(
        "--epoch-sec",
        type=int,
        default=None,
        help="Unix epoch seconds to set on the device; defaults to this host's current time.",
    )
    sync_time.add_argument(
        "--no-hwclock",
        action="store_true",
        help="Set only the system clock and skip writing the device RTC.",
    )
    sync_time.add_argument("--timeout-sec", type=float, default=60)
    sync_time.add_argument("--command-timeout-sec", type=float, default=60)
    sync_time.add_argument("--events", action="store_true")

    return parser


def add_simple_command(subparsers, name: str, handler):
    command = subparsers.add_parser(name)
    command.set_defaults(handler=handler)
    return command


def add_job_command(subparsers, name: str, handler):
    command = add_simple_command(subparsers, name, handler)
    command.add_argument("--wait", action="store_true")
    command.add_argument("--events", action="store_true")
    command.add_argument("--timeout-sec", type=float, default=600)
    return command


def add_connect_arguments(command, required_channel: bool = False) -> None:
    default_target = os.getenv("OH_AUTO_CONNECT_TARGET") or os.getenv("OH_AUTO_HDC_TARGET")
    command.add_argument(
        "--connect-channel",
        choices=["usb", "tcp", "uart"],
        required=required_channel,
        help="Select the HDC channel before running the operation.",
    )
    command.add_argument(
        "--connect-target",
        default=default_target,
        help="Select a concrete HDC connect key; may be provided by OH_AUTO_CONNECT_TARGET or OH_AUTO_HDC_TARGET.",
    )
    command.add_argument(
        "--connect-baudrate",
        type=int,
        help="Baudrate for uart connect selection.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        client = OhAutoClient(args.base_url, args.api_key, timeout_sec=args.timeout_sec)
        result = args.handler(client, args)
        print_json(result)
        return 0
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
