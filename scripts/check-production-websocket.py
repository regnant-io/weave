"""Verify HTTPS API routing and a live canvas WebSocket through Caddy.

Run this against a disposable deployment because registration creates one test
user. The project and canvas created by the test are deleted before exit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import uuid
from urllib.parse import quote
from urllib.request import Request, urlopen

import websockets


def request_json(
    origin: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
    verify_tls: bool = True,
) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    context = None if verify_tls else ssl._create_unverified_context()
    with urlopen(
        Request(origin.rstrip("/") + path, data=data, headers=headers, method=method),
        timeout=15,
        context=context,
    ) as response:
        return response.status, json.loads(response.read())


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="https://localhost")
    parser.add_argument(
        "--insecure-local-tls",
        action="store_true",
        help="accept Caddy's local development CA certificate",
    )
    args = parser.parse_args()
    verify = not args.insecure_local_tls
    phone = "+2557" + uuid.uuid4().hex[:8]

    status, registered = request_json(
        args.origin,
        "/api/v1/auth/register",
        method="POST",
        body={
            "phone": phone,
            "password": "production-smoke-password-123",
            "role": "researcher",
            "preferred_language": "en",
        },
        verify_tls=verify,
    )
    assert status == 201
    token = str(registered["access_token"])

    status, project = request_json(
        args.origin,
        "/api/v1/projects",
        method="POST",
        body={"title": "Production route smoke", "mode": "researcher"},
        token=token,
        verify_tls=verify,
    )
    assert status == 201
    project_id = str(project["id"])

    try:
        status, canvases = request_json(
            args.origin,
            f"/api/v1/projects/{quote(project_id)}/canvases",
            token=token,
            verify_tls=verify,
        )
        assert status == 200 and len(canvases) == 1
        canvas = canvases[0]

        status, ticket = request_json(
            args.origin,
            "/api/v1/ws-ticket",
            method="POST",
            token=token,
            verify_tls=verify,
        )
        assert status == 200
        ws_origin = args.origin.replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1
        )
        ws_url = (
            f"{ws_origin}/api/v1/ws/canvas/{quote(str(canvas['id']))}"
            f"?token={quote(str(ticket['token']))}"
        )
        tls = ssl._create_unverified_context() if not verify else None
        async with websockets.connect(ws_url, ssl=tls, open_timeout=15) as socket:
            snapshot = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
            assert snapshot["type"] == "snapshot"
            assert snapshot["canvas_id"] == canvas["id"]

            updated_content = "production websocket route verified"
            status, _updated = await asyncio.to_thread(
                request_json,
                args.origin,
                f"/api/v1/projects/{quote(project_id)}/canvases/{quote(str(canvas['id']))}",
                method="PUT",
                body={
                    "content": updated_content,
                    "base_revision": canvas["revision"],
                    "title": canvas["title"],
                },
                token=token,
                verify_tls=verify,
            )
            assert status == 200
            update = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
            assert update["type"] == "update"
            assert update["content"] == updated_content
    finally:
        request_json(
            args.origin,
            f"/api/v1/projects/{quote(project_id)}",
            method="DELETE",
            token=token,
            verify_tls=verify,
        )

    print("Production HTTPS and WebSocket contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
