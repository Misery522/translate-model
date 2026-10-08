"""运行不依赖 Android 的真实 Java 单测；编译与执行共用 60 秒截止时间。"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path


def run_java_tests(root: Path, jdk: Path) -> None:
    started = time.monotonic()
    tools = jdk / "bin"
    suffix = ".exe" if os.name == "nt" else ""
    for tool in ("java", "javac"):
        if not (tools / (tool + suffix)).is_file():
            raise ValueError("缺少明确指定的 JDK，不会退回全局解释器")
    release = (jdk / "release").read_text(encoding="utf-8")
    if not re.search(r'^JAVA_VERSION="21\.0\.12\.1"$', release, re.MULTILINE) or not re.search(
        r'^JAVA_RUNTIME_VERSION="21\.0\.12\.1\+1(?:[-"].*)?$', release, re.MULTILINE
    ):
        raise ValueError("JDK 版本不是固定的 Temurin 21.0.12.1+1")
    if any(os.environ.get(name) for name in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS")):
        raise ValueError("请先确认并移除当前终端的 JVM 覆盖项；不会暗中清除环境")
    source = root / "mobile/android/app/src"
    package = Path("java/io/github/misery522/yijing")
    files = [
        *sorted((source / "main" / package / "core").glob("*.java")),
        *sorted((source / "main" / package / "host").glob("*.java")),
        *sorted((source / "test" / package / "core").glob("*.java")),
        *sorted((source / "test" / package / "host").glob("*.java")),
    ]
    if len(files) < 7:
        raise ValueError("Java 源码或测试不完整")

    def call(*arguments: str) -> None:
        remaining = 60 - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(arguments[0], 60)
        # 测试不生成其他进程，超时只停止本脚本创建的 javac/java。
        subprocess.run(arguments, check=True, timeout=remaining, cwd=root)

    with tempfile.TemporaryDirectory(prefix="yijing-native-tests-") as generated:
        call(str(tools / ("javac" + suffix)), "-encoding", "UTF-8", "--release", "21",
             "-d", generated, *(str(file) for file in files))
        for name in ("core.NativeTranslatorCoreTest", "host.HostTests"):
            call(str(tools / ("java" + suffix)), "-cp", generated,
                 "io.github.misery522.yijing." + name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jdk-home", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        run_java_tests(Path(__file__).resolve().parents[1], arguments.jdk_home.resolve())
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Android Java tests failed or exceeded the shared 60-second limit.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
