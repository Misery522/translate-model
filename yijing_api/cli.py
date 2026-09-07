"""本机启动 API；终端输入 p 可生成下一次配对码。"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

import uvicorn

from .app import create_app
from .config import ApiSettings
from .static import mount_static_shell


def main() -> None:
    parser = argparse.ArgumentParser(description="启动译境私人 API")
    parser.add_argument("--port", type=int, default=int(os.getenv("YIJING_API_PORT", "8765")))
    parser.add_argument("--public-origin", default=os.getenv("YIJING_PUBLIC_ORIGIN"))
    parser.add_argument("--client-origin", action="append", default=[])
    parser.add_argument("--static-dir", type=Path, help="前端构建目录，例如 web/dist；不指定则只启动 API")
    args = parser.parse_args()
    try:
        settings = ApiSettings(
            port=args.port,
            public_origin=args.public_origin or f"http://127.0.0.1:{args.port}",
            client_origins=tuple(args.client_origin),
        )
    except ValueError:
        parser.error("端口或可信服务地址配置无效。")
    app = create_app(settings)
    if args.static_dir is not None:
        try:
            mount_static_shell(app, args.static_dir)
        except (OSError, ValueError):
            parser.error("网页目录无效，请先在 web 目录执行 npm ci 和 npm run build。")
    print(f"译境私人服务：{settings.public_origin}")
    print("网页界面已挂载。" if args.static_dir is not None else "仅 API 模式；网页需要 --static-dir web/dist。")
    print(f"一次性配对码（5 分钟有效）：{app.state.pairing_code}")
    app.state.pairing_code = None
    print("需要连接下一台设备时，在本机终端输入 p 并按 Enter。")

    def local_commands() -> None:
        for line in sys.stdin:
            if line.strip().lower() == "p":
                print(f"新的一次性配对码：{app.state.auth.issue_pair_code()}", flush=True)

    if sys.stdin.isatty():
        threading.Thread(target=local_commands, daemon=True, name="local-pairing-console").start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.port,
        workers=1,
        proxy_headers=False,
        access_log=False,
        limit_concurrency=32,
        timeout_keep_alive=5,
    )


if __name__ == "__main__":
    main()
