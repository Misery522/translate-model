"""项目专用 Android 启动器不能更改全局环境或依赖真实 SDK 才能测试。"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "android-env.ps1"


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_probe(source: str, *, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("动态测试需要 PowerShell 7，不要求 Android SDK 或 JDK 安装")
    probe = (
        "$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        f". {powershell_literal(str(SCRIPT))}; {source}"
    )
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def fixture_toolchain(tmp_path: Path, missing: str = "") -> tuple[Path, Path, Path]:
    jdk = tmp_path / "jdk"
    sdk = tmp_path / "sdk"
    gradle = tmp_path / "gradle"
    required_files = {
        jdk / "bin/java.exe": "",
        jdk / "bin/javac.exe": "",
        jdk / "release": 'JAVA_VERSION="21.0.12.1"\n'
        'JAVA_RUNTIME_VERSION="21.0.12.1+1-LTS"\n',
        sdk / "cmdline-tools/22.0/lib/sdkmanager-classpath.jar": "",
        sdk / "cmdline-tools/22.0/source.properties": "Pkg.Revision=22.0\n",
        sdk / "platforms/android-36/android.jar": "",
        sdk / "platforms/android-36/source.properties": "AndroidVersion.ApiLevel=36\n",
        sdk / "build-tools/36.0.0/aapt2.exe": "",
        sdk / "build-tools/36.0.0/source.properties": "Pkg.Revision=36.0.0\n",
        gradle / "lib/gradle-gradle-cli-main-8.14.3.jar": "",
        gradle / "lib/agents/gradle-instrumentation-agent-8.14.3.jar": "",
    }
    omitted = {
        "cmdline": sdk / "cmdline-tools/22.0/lib/sdkmanager-classpath.jar",
        "gradle": gradle / "lib/gradle-gradle-cli-main-8.14.3.jar",
        "platform": sdk / "platforms/android-36/android.jar",
    }.get(missing)
    for path, contents in required_files.items():
        if path == omitted or (missing == "sdk" and sdk in path.parents):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    return jdk, sdk, gradle


def probe_toolchain(tmp_path: Path, layout: tuple[Path, Path, Path]) -> str:
    jdk, sdk, gradle = layout
    return (
        "try { Get-AndroidToolchain doctor "
        f"{powershell_literal(str(jdk))} {powershell_literal(str(sdk))} "
        f"{powershell_literal(str(gradle))} {powershell_literal(str(tmp_path / 'cache'))} "
        "} catch { Write-Output $_.Exception.Message; exit 0 }; exit 4"
    )


def test_script_uses_child_environment_and_no_shell_or_global_mutation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "#requires -Version 7.0" in source
    assert "$startInfo.ArgumentList.Add($argument)" in source
    assert "$startInfo.UseShellExecute = $false" in source
    assert "$process.Kill($true)" in source
    for variable in ("JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "GRADLE_USER_HOME"):
        assert f"$startInfo.Environment['{variable}']" in source
    for forbidden in (
        "SetEnvironmentVariable(",
        "$env:PATH =",
        "$env:JAVA_HOME =",
        "Invoke-Expression",
        "cmd.exe",
        "taskkill",
        "Stop-Process",
        "Remove-Item",
    ):
        assert forbidden not in source


def test_direct_arguments_and_child_environment_do_not_change_parent(tmp_path: Path) -> None:
    arguments = ["", "空格 路径", 'quote"value', "semicolon;value", "$(not-run)", "tail\\"]
    native_arguments = ",".join(powershell_literal(value) for value in arguments)
    source = f"""
        Set-Location -LiteralPath {powershell_literal(str(tmp_path))};
        $layout = @{{JdkHome='fixture-jdk'; SdkRoot='fixture-sdk'; GradleUserHome='fixture-cache'}};
        $before = @{{PATH=$env:PATH; JAVA_HOME=$env:JAVA_HOME; ANDROID_HOME=$env:ANDROID_HOME;
            ANDROID_SDK_ROOT=$env:ANDROID_SDK_ROOT; GRADLE_USER_HOME=$env:GRADLE_USER_HOME}};
        $payload = 'import json,os,sys;print(json.dumps({{"args":sys.argv[1:],"java":os.environ["JAVA_HOME"],"sdk":os.environ["ANDROID_HOME"],"sdkRoot":os.environ["ANDROID_SDK_ROOT"],"cache":os.environ["GRADLE_USER_HOME"],"cwd":os.getcwd()}},ensure_ascii=False))';
        [Console]::Error.WriteLine('fixture: launching isolated child');
        $code = Invoke-AndroidProcess {powershell_literal(sys.executable)} `
            (@('-I', '-S', '-X', 'utf8', '-c', $payload) + @({native_arguments})) $layout 5;
        [Console]::Error.WriteLine('fixture: child and output completed');
        if ($code -ne 0) {{ throw "fixture child exit code: $code" }};
        foreach($name in $before.Keys) {{
            if([Environment]::GetEnvironmentVariable($name,'Process') -cne $before[$name]) {{
                throw "父进程变量发生改变：$name"
            }}
        }};
    """
    result = run_probe(source)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "args": arguments,
        "java": "fixture-jdk",
        "sdk": "fixture-sdk",
        "sdkRoot": "fixture-sdk",
        "cache": "fixture-cache",
        "cwd": str(tmp_path),
    }


@pytest.mark.parametrize(
    "argument",
    [
        "--daemon",
        "--foreground",
        "-g",
        "-gunexpected",
        "--gradle-user-home=unexpected",
        "-Porg.gradle.java.installations.auto-download=true",
        "-Dorg.gradle.java.home=unexpected",
        "-Dorg.gradle.daemon=true",
        "-Pandroid.overridePathCheck=true",
    ],
)
def test_gradle_cannot_override_fixed_runtime_controls(argument: str) -> None:
    result = run_probe(
        f"try {{ Get-AndroidJavaArguments gradle @{{}} @({powershell_literal(argument)}) }} "
        "catch { Write-Output 'rejected'; exit 0 }; exit 4"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "rejected"


@pytest.mark.parametrize(
    "argument", ["--sdk_root=unexpected", "--channel=3", "--no_https", "--no_https=true"]
)
def test_sdk_cannot_override_root_stability_or_https(argument: str) -> None:
    result = run_probe(
        f"try {{ Get-AndroidJavaArguments sdk @{{}} @({powershell_literal(argument)}) }} "
        "catch { Write-Output 'rejected'; exit 0 }; exit 4"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "rejected"


def test_gradle_uses_project_property_to_disable_jdk_download() -> None:
    result = run_probe(
        "$layout=@{JdkHome='fixture-jdk';GradleCliJar='fixture-cli';"
        "GradleInstrumentationAgent='fixture-agent'}; "
        "ConvertTo-Json -InputObject @(Get-AndroidJavaArguments gradle $layout @('--version')) -Compress"
    )
    assert result.returncode == 0, result.stderr
    arguments = json.loads(result.stdout)
    assert "-javaagent:fixture-agent" in arguments
    assert "-jar" in arguments
    assert "fixture-cli" in arguments
    assert "--no-daemon" in arguments
    assert "-Porg.gradle.java.installations.auto-download=false" in arguments
    assert "-Porg.gradle.java.installations.auto-detect=false" in arguments
    assert "-Porg.gradle.java.installations.paths=fixture-jdk" in arguments
    assert arguments[-1] == "--version"


def test_missing_java_fails_without_starting_tools(tmp_path: Path) -> None:
    missing = tmp_path / "missing-java.exe"
    result = run_probe(
        f"try {{ Get-AndroidRequiredFile {powershell_literal(str(missing))} 'JDK java.exe' }} "
        "catch { Write-Output $_.Exception.Message; exit 0 }; exit 4"
    )
    assert result.returncode == 0, result.stderr
    assert "JDK java.exe" in result.stdout
    assert "缺少" in result.stdout


def test_cli_failure_preserves_exit_status_under_stop_preference(tmp_path: Path) -> None:
    result = run_probe(
        f"& {powershell_literal(str(SCRIPT))} -Mode doctor "
        f"-JdkHome {powershell_literal(str(tmp_path / 'missing-jdk'))}; "
        "$code=$LASTEXITCODE; Write-Output $code; exit 0"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"
    assert result.stderr, "应显示缺失工具错误，不能静默成功"


@pytest.mark.skipif(os.name != "nt", reason="Windows 工具布局模拟，不要求真实 SDK 安装")
@pytest.mark.parametrize(
    "missing,label",
    [
        ("sdk", "Android SDK"),
        ("cmdline", "SDK 命令行工具 22.0"),
        ("gradle", "Gradle 8.14.3 CLI"),
        ("platform", "SDK Platform 36 android.jar"),
    ],
)
def test_missing_toolchain_parts_fail_clearly(
    tmp_path: Path, missing: str, label: str
) -> None:
    result = run_probe(probe_toolchain(tmp_path, fixture_toolchain(tmp_path, missing)))
    assert result.returncode == 0, result.stderr
    assert label in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows 工具布局模拟，不要求真实 SDK 安装")
@pytest.mark.parametrize(
    "relative,content,label",
    [
        ("jdk/release", 'JAVA_VERSION="25.0.2"\n', "JDK 版本不是已锁定"),
        ("sdk/cmdline-tools/22.0/source.properties", "Pkg.Revision=23.0\n", "固定版本 22.0"),
        ("sdk/platforms/android-36/source.properties", "AndroidVersion.ApiLevel=37\n", "不会把 API 37"),
        ("sdk/build-tools/36.0.0/source.properties", "Pkg.Revision=35.0.0\n", "必须为 36.0.0"),
    ],
)
def test_wrong_tool_versions_are_not_silently_accepted(
    tmp_path: Path, relative: str, content: str, label: str
) -> None:
    layout = fixture_toolchain(tmp_path)
    (tmp_path / relative).write_text(content, encoding="utf-8")
    result = run_probe(probe_toolchain(tmp_path, layout))
    assert result.returncode == 0, result.stderr
    assert label in result.stdout


def test_tool_exit_code_is_preserved() -> None:
    result = run_probe(
        "$layout=@{JdkHome='fixture-jdk';SdkRoot='fixture-sdk';GradleUserHome='fixture-cache'}; "
        f"$code=Invoke-AndroidProcess {powershell_literal(sys.executable)} "
        "@('-c','import sys;sys.exit(7)') $layout 5; Write-Output $code"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "7"


def test_timeout_is_reported_without_waiting_for_tool_completion() -> None:
    result = run_probe(
        "$layout=@{JdkHome='fixture-jdk';SdkRoot='fixture-sdk';GradleUserHome='fixture-cache'}; "
        f"try {{ Invoke-AndroidProcess {powershell_literal(sys.executable)} "
        "@('-c','import time;time.sleep(20)') $layout 1 } "
        "catch [TimeoutException] { Write-Output 'timed-out'; exit 0 }; exit 4"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "timed-out"


def test_exited_parent_with_inherited_pipe_cannot_bypass_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "pipe-child.pid"
    payload = (
        "import pathlib,subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(8)'],"
        "stdout=sys.stdout,stderr=sys.stderr,"
        "creationflags=0x08000000 if sys.platform=='win32' else 0);"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid));"
        "sys.exit(0)"
    )
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(20)"],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        result = run_probe(
            "$layout=@{JdkHome='fixture-jdk';SdkRoot='fixture-sdk';GradleUserHome='fixture-cache'}; "
            f"try {{ Invoke-AndroidProcess {powershell_literal(sys.executable)} "
            f"@('-c',{powershell_literal(payload)}) $layout 1 }} "
            "catch [TimeoutException] { Write-Output 'pipe-timed-out'; exit 0 }; exit 4",
            timeout=7,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "pipe-timed-out"
        assert unrelated.poll() is None
        assert pid_file.exists(), "fixture 必须确实产生持有管道的子进程"
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
        if pid_file.exists():
            fixture_pid = int(pid_file.read_text(encoding="utf-8"))
            try:
                os.kill(fixture_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_document_does_not_confuse_environment_with_app_delivery() -> None:
    documentation = SCRIPT.parents[1] / "docs" / "ANDROID_ENVIRONMENT.md"
    text = documentation.read_text(encoding="utf-8")
    assert "不是可安装 App 的交付说明" in text
    assert "compileDebugJavaWithJavac" in text
    assert "不生成或分发 APK" in text
    assert os.path.isabs(str(SCRIPT))
