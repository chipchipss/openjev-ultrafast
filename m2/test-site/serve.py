"""M2 test-site 静态服务器。

用法：python3 m2/test-site/serve.py --port 8765
约束：无外部依赖（stdlib http.server）；目录 = 脚本所在目录。
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 安静模式，e2e 日志不被刷屏
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    directory = Path(__file__).resolve().parent
    handler = partial(Handler, directory=str(directory))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"serving {directory} at http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
