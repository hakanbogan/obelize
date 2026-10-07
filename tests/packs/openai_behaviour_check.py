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
from http.server import BaseHTTPRequestHandler, HTTPServer

import openai


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        if self.path.endswith("/chat/completions"):
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
    if hasattr(openai, "api_base"):
        openai.api_base = url
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
            print(f"{name}.{function.__name__} = {function('ping')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
