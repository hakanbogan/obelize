"""Runs each openai fixture against a local server and prints what its functions return.

The legacy fixtures run on 0.28.1 and their answer keys on a new release; the weekly end-to-end
job diffs the two outputs, which is what "the migrated call does what the old one did" rests on.
Standard library only, so nothing but the SDK is installed (0.28.1 also needs numpy to read an
embedding, which it asks for as base64).

    python -I tests/packs/openai_behaviour_check.py <fixture.py>...
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import re
import runpy
import struct
import sys
import threading
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import openai


def form(content_type: str, raw: bytes) -> dict[str, str]:
    """The fields of a multipart body; the uploaded file is only said to be there, as the answer
    keys and the legacy fixtures are not the same file."""
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + raw
    )
    fields = {}
    for part in message.iter_parts():
        name = str(part.get_param("name", header="content-disposition"))
        fields[name] = "uploaded" if name == "file" else str(part.get_content())
    return fields


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        content_type = self.headers["Content-Type"]
        body: dict[str, Any] = (
            form(content_type, raw) if content_type.startswith("multipart/") else json.loads(raw)
        )
        usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        answer: dict[str, Any]
        if self.path.endswith("/audio/transcriptions") or self.path.endswith("/audio/translations"):
            answer = {"text": f"{self.path.rsplit('/', 1)[1]} {sorted(body.items())}"}
        elif self.path.endswith("/images/generations"):
            picture = {"url": "url " + body["prompt"]}
            answer = {"created": 1, "data": [picture] * body.get("n", 1)}
        elif self.path.endswith("/moderations"):
            answer = {
                "id": "m1",
                "model": body.get("model", "text-moderation-latest"),
                "results": [{"flagged": "in" in body["input"], "categories": {}}],
            }
        elif self.path.endswith("/chat/completions"):
            message = {"role": "assistant", "content": "chat " + body["messages"][-1]["content"]}
            answer = {
                "id": "c1",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}]
                * body.get("n", 1),
                "usage": usage,
            }
        elif self.path.endswith("/embeddings"):
            vector = [0.5, 0.25]
            held: object = vector
            if body.get("encoding_format") == "base64":
                held = base64.b64encode(struct.pack("<2f", *vector)).decode()
            answer = {
                "object": "list",
                "model": body["model"],
                "data": [{"object": "embedding", "index": 0, "embedding": held}],
                "usage": usage,
            }
        else:
            choice = {"index": 0, "finish_reason": "stop", "text": "text " + str(body["prompt"])}
            answer = {
                "id": "t1",
                "object": "text_completion",
                "created": 1,
                "model": body["model"],
                "choices": [choice],
                "usage": usage,
            }
        data = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        """Silent: the output is the comparison."""


def main(paths: list[str]) -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/v1"
    os.environ["OPENAI_API_KEY"] = "unused"
    # Without the trailing slash the new module client would join a route onto `/v1` unseparated.
    os.environ["MOCK_URL"] = url
    if hasattr(openai, "api_base"):
        openai.api_base = url
        # 0.28.1 read the key when it was imported, before the line above set it.
        openai.api_key = "unused"
    else:
        openai.base_url = url + "/"
    for path in paths:
        name = re.sub(r"\.(before|after)\.py$", "", os.path.basename(path))
        namespace = runpy.run_path(path)
        functions = [
            value
            for value in namespace.values()
            if inspect.isfunction(value) and value.__module__ == namespace["__name__"]
        ]
        for function in sorted(functions, key=lambda value: value.__name__):
            # A function that takes a `path` is handed a file to upload.
            argument = path if "path" in inspect.signature(function).parameters else "ping"
            print(f"{name}.{function.__name__} = {function(argument)!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
