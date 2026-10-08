"""统一进度随开发更新，确保源码包内能找到当前方案与验收边界。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "PROJECT_STATUS.md"


def test_progress_items_keep_results_evidence_and_next_actions_separate():
    source = STATUS.read_text(encoding="utf-8")
    items = re.split(r"^### \d+\..*$", source, flags=re.MULTILINE)[1:]
    assert items, "统一进度应包含分项，不仅是一段总结"
    for item in items:
        for field in ("状态", "本次结果", "验证依据", "剩余问题", "下一步"):
            assert f"**{field}：" in item
    assert "不设置后台定时任务" in source


def test_current_plan_entrypoints_resolve_in_source_archive():
    paths = (
        "README.md", "docs/PROJECT_STATUS.md", "docs/ANDROID_APP_PLAN.md",
        "docs/ANDROID_NATIVE.md", "docs/PRIVATE_DEPLOYMENT.md",
        "docs/M2_ACCEPTANCE.md", "docs/ROADMAP.md",
        "docs/REDMI_ACCEPTANCE.md", "docs/NEXT_FEATURE_DESIGN.md",
    )
    for path in paths:
        document = ROOT / path
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if "://" not in target and not target.startswith("#"):
                assert (document.parent / target.split("#", 1)[0]).exists(), (path, target)


def test_replaced_android_plan_does_not_claim_device_acceptance():
    source = (ROOT / "docs" / "ANDROID_APP_PLAN.md").read_text(encoding="utf-8")
    assert "原方案已替代" in source
    assert "PROJECT_STATUS.md" in source and "ANDROID_NATIVE.md" in source
    assert "暂不安装手机" in source
    assert "APK 构建成功不等于真机验收" in source


def test_redmi_record_and_future_design_do_not_claim_authorization():
    acceptance = (ROOT / "docs" / "REDMI_ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "暂不安装" in acceptance and "未验证" in acceptance
    assert "INTERNET" in acceptance and "不一定出现授权弹窗" in acceptance
    design = (ROOT / "docs" / "NEXT_FEATURE_DESIGN.md").read_text(encoding="utf-8")
    assert "不表示用户已批准" in design
    assert "32 KiB" in design and "不能往文本字段塞音频" in design
