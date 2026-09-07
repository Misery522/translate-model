"""保证发布产物缺件与恶意路径不会被验证器放过。"""

import pytest

from scripts.verify_distributions import (
    REQUIRED_SOURCE,
    RUNTIME_MODULES,
    validate_archive_paths,
    validate_source_members,
    validate_wheel_members,
)


@pytest.mark.parametrize("name", ["../escape.py", "/absolute.py", "a/../../escape.py", "C:/x.py", "a\\b.py"])
def test_archive_rejects_paths_outside_destination(name):
    with pytest.raises(ValueError, match="Unsafe archive member"):
        validate_archive_paths([name])


@pytest.mark.parametrize("missing", [
    "scripts/audit_publication.py", "data/glossary.example.json", "uv.lock", "LICENSE",
])
def test_source_archive_requires_offline_test_and_license_inputs(missing):
    names = ["release/" + name for name in REQUIRED_SOURCE - {missing}]
    with pytest.raises(ValueError, match="missing required files"):
        validate_source_members(names)


def test_complete_source_archive_has_one_safe_root():
    assert validate_source_members(["release/" + name for name in REQUIRED_SOURCE]) == "release"


def test_wheel_requires_runtime_paths_and_license():
    names = [f"{module}.py" for module in RUNTIME_MODULES]
    names.append("release.dist-info/licenses/THIRD_PARTY_NOTICES.md")
    with pytest.raises(ValueError, match="LICENSE"):
        validate_wheel_members(names)
    names.append("release.dist-info/licenses/LICENSE")
    validate_wheel_members(names)
