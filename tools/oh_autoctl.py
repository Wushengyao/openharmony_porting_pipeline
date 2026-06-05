#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_BASE_URL = "http://127.0.0.1:8787/api/v1"


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

        boundary = f"oh_auto_{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
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


def command_status(client: OhAutoClient, args: argparse.Namespace) -> Any:
    return client.request_json("GET", f"/devices/{args.device_id}/status")


def command_preflight(client: OhAutoClient, args: argparse.Namespace) -> Any:
    health = client.request_json("GET", "/health")
    capabilities = client.request_json("GET", "/capabilities")
    status = client.request_json("GET", f"/devices/{args.device_id}/status")
    templates = {
        item.get("template_id"): item
        for item in capabilities.get("flash_templates", [])
        if isinstance(item, dict)
    }
    connected_targets = [
        item
        for item in status.get("hdc", {}).get("targets", [])
        if item.get("status") in {None, "Connected"} or item.get("status", "").lower() == "connected"
    ]
    checks = {
        "health_ok": health.get("status") == "ok",
        "device_exists": any(
            item.get("device_id") == args.device_id for item in capabilities.get("devices", [])
        ),
        "template_available": templates.get(args.template_id, {}).get("valid") is True,
        "device_connected": bool(connected_targets),
        "device_unlocked": not status.get("device_locked", False),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "health": health,
        "template_id": args.template_id,
        "connected_targets": connected_targets,
        "running_jobs": status.get("running_jobs", []),
    }


def command_upload(client: OhAutoClient, args: argparse.Namespace) -> Any:
    result = client.upload(Path(args.file))
    if args.id_only:
        print(result["artifact_id"])
        return None
    return result


def command_shell(client: OhAutoClient, args: argparse.Namespace) -> Any:
    command = args.command if len(args.command) != 1 else args.command[0]
    if isinstance(command, list):
        command = " ".join(command)
    job = client.request_json(
        "POST",
        f"/devices/{args.device_id}/ops/shell",
        {"command": command, "timeout_sec": args.command_timeout_sec},
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
    commands = [
        "echo oh_auto_agent_smoke_ok",
        "param get const.product.name",
        "param get const.ohos.fullname",
        "uname -a",
    ]
    results = []
    for command in commands:
        job = client.request_json(
            "POST",
            f"/devices/{args.device_id}/ops/shell",
            {"command": command, "timeout_sec": args.command_timeout_sec},
        )
        finished = client.request_json(
            "POST",
            f"/jobs/{job['job_id']}/wait?timeout_sec={args.timeout_sec}",
            {},
            timeout_sec=args.timeout_sec + 5,
        )
        stdout = client.request_json("GET", f"/jobs/{job['job_id']}/logs?stream=stdout&offset=0")
        results.append({"command": command, "job": finished, "stdout": stdout.get("content", "")})
        if finished.get("status") != "succeeded":
            break
    return {"ok": all(item["job"].get("status") == "succeeded" for item in results), "results": results}


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

    subparsers = parser.add_subparsers(dest="command_name", required=True)
    add_simple_command(subparsers, "health", command_health)
    add_simple_command(subparsers, "version", command_version)
    add_simple_command(subparsers, "capabilities", command_capabilities)
    add_simple_command(subparsers, "status", command_status)

    preflight = add_simple_command(subparsers, "preflight", command_preflight)
    preflight.add_argument("--template-id", default="musepaper2-titan")

    upload = add_simple_command(subparsers, "upload", command_upload)
    upload.add_argument("file")
    upload.add_argument("--id-only", action="store_true")

    shell = add_job_command(subparsers, "shell", command_shell)
    shell.add_argument("command", nargs="+")
    shell.add_argument("--command-timeout-sec", type=float, default=300)

    flash = add_job_command(subparsers, "flash", command_flash)
    flash.add_argument("template_id")
    flash.add_argument("--image", help="Artifact id or allowed Windows local path for artifacts.image")
    flash.add_argument("--artifact", action="append", default=[], help="Artifact mapping, name=value")
    flash.add_argument("--param", action="append", default=[], help="Template parameter, name=value")

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
    smoke.add_argument("--timeout-sec", type=float, default=60)
    smoke.add_argument("--command-timeout-sec", type=float, default=60)

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
