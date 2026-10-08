"""核验内部 APK 的内置界面、完整许可证与实际安装权限；不上传或安装。"""

from __future__ import annotations

import argparse
import re
import subprocess
import zipfile
from pathlib import Path


def verify_badging(metadata: str) -> None:
    """只接受固定工具链报告的应用身份、SDK 和唯一安装权限。"""
    metadata = "\n".join(metadata.splitlines())
    permissions = re.findall(r"^uses-permission[^:]*: name='([^']+)'", metadata, re.MULTILINE)
    if permissions != ["android.permission.INTERNET"]:
        raise ValueError("APK 合并后的权限超出预期")
    expected = {
        "minSdkVersion": "26",
        "targetSdkVersion": "36",
    }
    for field, value in expected.items():
        if re.findall(rf"^{field}:'([^']+)'$", metadata, re.MULTILINE) != [value]:
            raise ValueError("APK 安装要求不符合固定方案")
    if re.findall(r"^package: name='([^']+)'", metadata, re.MULTILINE) != [
        "io.github.misery522.yijing.alpha"
    ]:
        raise ValueError("APK 应用身份不符合固定方案")


def verify_apk(root: Path, apk: Path, aapt2: Path) -> None:
    with zipfile.ZipFile(apk) as archive:
        names = set(archive.namelist())
        expected = {
            "assets/public/index.html": root / "mobile/dist/index.html",
            "assets/public/notices/LICENSE.txt": root / "LICENSE",
            "assets/public/notices/THIRD_PARTY_LICENSES.txt": root / "mobile/dist/THIRD_PARTY_LICENSES.txt",
            "assets/public/notices/THIRD_PARTY_ANDROID_NOTICES.txt": root / "mobile/THIRD_PARTY_ANDROID_NOTICES.md",
        }
        for name, source in expected.items():
            if archive.read(name) != source.read_bytes():
                raise ValueError("APK 界面或许可与源码不一致")
        for source in (root / "mobile/dist/assets").iterdir():
            if archive.read("assets/public/assets/" + source.name) != source.read_bytes():
                raise ValueError("APK 静态资源与本次构建不一致")
        if any(name.endswith(("sw.js", ".webmanifest", ".map", ".keystore", ".jks")) for name in names):
            raise ValueError("APK 含有非原生入口资源或私密签名文件")
        if "classes.dex" not in names:
            raise ValueError("APK 缺少原生代码")
    result = subprocess.run([str(aapt2), "dump", "badging", str(apk)],
                            check=True, capture_output=True, timeout=30)
    metadata = result.stdout.decode("utf-8", errors="strict")
    verify_badging(metadata)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--aapt2", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        verify_apk(Path(__file__).resolve().parents[1], arguments.apk, arguments.aapt2)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError):
        print("Private APK validation failed; do not install or distribute.")
        return 1
    print("Private APK resources, complete licenses, API 26/36 and INTERNET-only permissions verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
