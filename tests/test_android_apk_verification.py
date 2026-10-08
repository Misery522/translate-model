"""真实工具输出格式的回归；不安装或执行 APK。"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify-android-apk.py"
SPEC = importlib.util.spec_from_file_location("android_apk_verification", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BADGING = "\n".join([
    "package: name='io.github.misery522.yijing.alpha' versionCode='1'",
    "minSdkVersion:'26'",
    "targetSdkVersion:'36'",
    "uses-permission: name='android.permission.INTERNET'",
])


def test_fixed_aapt2_badging_format():
    MODULE.verify_badging(BADGING)
    MODULE.verify_badging(BADGING.replace("\n", "\r\n"))


@pytest.mark.parametrize("metadata", [
    BADGING.replace("minSdkVersion:'26'", "minSdkVersion:'25'"),
    BADGING.replace("targetSdkVersion:'36'", "targetSdkVersion:'35'"),
    BADGING.replace("yijing.alpha", "another.app"),
    BADGING + "\nuses-permission: name='android.permission.RECORD_AUDIO'",
    BADGING + "\nuses-permission-sdk-23: name='android.permission.CAMERA'",
    BADGING + "\nminSdkVersion:'26'",
    BADGING.replace("minSdkVersion:'26'", "unrelated minSdkVersion:'26'"),
])
def test_rejects_unexpected_sdk_identity_permissions_and_duplicates(metadata):
    with pytest.raises(ValueError):
        MODULE.verify_badging(metadata)
