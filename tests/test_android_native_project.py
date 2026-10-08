"""无 SDK 时也能检查 Android 源码安全基线；不冒充设备或原生运行测试。"""

from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile/android"
NS = "{http://schemas.android.com/apk/res/android}"


def test_native_manifest_minimal_permissions_and_no_backups():
    manifest = ElementTree.parse(ANDROID / "app/src/main/AndroidManifest.xml").getroot()
    assert [item.attrib[NS + "name"] for item in manifest.findall("uses-permission")] == [
        "android.permission.INTERNET"
    ]
    application = manifest.find("application")
    assert application is not None
    assert application.attrib[NS + "allowBackup"] == "false"
    assert application.attrib[NS + "usesCleartextTraffic"] == "false"
    assert application.attrib[NS + "fullBackupContent"] == "@xml/backup_rules"
    assert application.attrib[NS + "dataExtractionRules"] == "@xml/data_extraction_rules"
    assert not application.findall("provider")
    assert not application.findall("service")


def test_cloud_and_device_transfer_exclusions():
    rules = ElementTree.parse(ANDROID / "app/src/main/res/xml/data_extraction_rules.xml")
    for kind in ("cloud-backup", "device-transfer"):
        element = rules.getroot().find(kind)
        assert element is not None
        assert {item.attrib["domain"] for item in element.findall("exclude")} == {
            "root", "file", "database", "sharedpref", "external"
        }


def test_native_entry_is_not_pwa_or_remote_network():
    html = (ROOT / "mobile/index.html").read_text(encoding="utf-8")
    assert "connect-src 'none'" in html
    for key in ("worker-src", "frame-src", "object-src", "base-uri", "form-action"):
        assert key + " 'none'" in html
    assert "unsafe-inline" not in html and "unsafe-eval" not in html
    main = (ROOT / "mobile/src/main.tsx").read_text(encoding="utf-8")
    assert "serviceWorker" not in main and "localStorage" not in main
    assert "fetch(" not in main


def test_no_legacy_bridge_or_tls_bypass():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (
        ANDROID / "app/src/main/java"
    ).rglob("*.java"))
    for forbidden in ("addJavascriptInterface(", "setHostnameVerifier(", "setSSLSocketFactory(",
                      "SslErrorHandler", "SharedPreferences", "Log.d(", "saveState("):
        assert forbidden not in sources
    assert "WEB_MESSAGE_LISTENER" in sources
    assert "FLAG_SECURE" in sources
    assert "IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS" in sources
    assert "setInstanceFollowRedirects(false)" in sources


def test_fixed_android_build_and_verification_metadata():
    build = (ANDROID / "app/build.gradle").read_text(encoding="utf-8")
    assert "minSdk 26" in build and "targetSdk 36" in build
    assert "androidx.webkit:webkit:1.14.0" in build
    assert "lockAllConfigurations()" in build
    assert "android.overridePathCheck" not in build
    metadata = ElementTree.parse(ANDROID / "gradle/verification-metadata.xml")
    hashes = metadata.findall(".//{https://schema.gradle.org/dependency-verification}sha256")
    assert hashes and all(len(item.attrib["value"]) == 64 for item in hashes)


def test_android_sources_distributed_but_not_apk():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include mobile" in manifest
    assert "scripts/run-android-unit-tests.py" in manifest
    assert "*.apk" not in manifest
