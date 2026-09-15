"""Prove that a dropped chat stream resumes without gaps or duplicate events.

The target must use Redis and a Celery worker. The script registers a disposable
user, creates one project, disconnects after the first durable event, resumes from
that exact sequence, and deletes the project. The user row remains for auditability.
"""
from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Iterator
from urllib.parse import quote
from urllib.request import Request, urlopen


def request_json(
    origin: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(
        Request(origin.rstrip("/") + path, data=data, headers=headers, method=method),
        timeout=30,
    ) as response:
        return response.status, json.loads(response.read())


def open_stream(
    origin: str,
    path: str,
    *,
    token: str,
    body: dict | None = None,
):
    headers = {"Accept": "text/event-stream", "Authorization": f"Bearer {token}"}
    data = None
    method = "GET"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
        method = "POST"
    return urlopen(
        Request(origin.rstrip("/") + path, data=data, headers=headers, method=method),
        timeout=60,
    )


def events(response) -> Iterator[tuple[str, dict]]:
    event_name = "message"
    data_lines: list[str] = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data_lines:
                yield event_name, json.loads("\n".join(data_lines))
            event_name = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    phone = f"+2557{uuid.uuid4().int % 100_000_000:08d}"

    status, registered = request_json(
        args.origin,
        "/api/v1/auth/register",
        method="POST",
        body={
            "phone": phone,
            "password": "stream-resume-smoke-password-123",
            "role": "researcher",
            "preferred_language": "en",
        },
    )
    assert status == 201
    token = str(registered["access_token"])
    status, project = request_json(
        args.origin,
        "/api/v1/projects",
        method="POST",
        body={"title": "Stream resume smoke", "mode": "researcher"},
        token=token,
    )
    assert status == 201
    project_id = str(project["id"])

    try:
        response = open_stream(
            args.origin,
            f"/api/v1/projects/{quote(project_id)}/messages",
            token=token,
            body={
                "content": "Explain in two short sentences why durable streams matter.",
                "language": "en",
                "stream": True,
                "effort": "spool",
                "services": {},
            },
        )
        turn_id = ""
        before: list[int] = []
        with response:
            for event, data in events(response):
                if event == "turn":
                    turn_id = str(data.get("turn_id") or "")
                if "seq" in data:
                    before.append(int(data["seq"]))
                    break
        assert turn_id and before == [0], (turn_id, before)

        resumed: list[int] = []
        names: list[str] = []
        with open_stream(
            args.origin,
            f"/api/v1/turns/{quote(turn_id)}/stream?after={before[-1]}",
            token=token,
        ) as response:
            for event, data in events(response):
                names.append(event)
                if "seq" in data:
                    resumed.append(int(data["seq"]))

        assert "resume_gap" not in names
        assert "error" not in names
        assert "done" in names
        assert resumed and resumed == sorted(set(resumed))
        assert min(resumed) == before[-1] + 1
        assert not set(before) & set(resumed)
    finally:
        request_json(
            args.origin,
            f"/api/v1/projects/{quote(project_id)}",
            method="DELETE",
            token=token,
        )

    print(
        f"Stream resume contract passed for turn {turn_id[:8]} "
        f"({len(resumed)} replayed events)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
