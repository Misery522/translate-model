"""为源码运行和 wheel 安装选择可写的用户数据目录。"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_path


def data_directory(module_path: Path | None = None) -> Path:
    configured = os.getenv("YIJING_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    root = (module_path or Path(__file__)).resolve().parent
    if (root / "pyproject.toml").is_file():
        return root / "data"
    # 安装后的 wheel 不能把个人词库写进 site-packages。
    return user_data_path("Yijing", appauthor=False)
