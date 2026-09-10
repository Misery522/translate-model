"""从本地类型导出公开协议，不连接模型、不访问运行中的服务。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from yijing_api.app import create_app


def schema_text() -> str:
    app = create_app()
    schema = app.openapi()
    # 配对凭据仅在运行时使用，不得出现在生成文件中。
    app.state.auth.clear()
    app.state.pairing_code = None
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("web/openapi.json"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = schema_text()
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != expected:
            raise SystemExit("OpenAPI 文件已过期，请重新生成后提交。")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    main()
