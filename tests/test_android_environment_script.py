"""项目专用 Android 启动器不能更改全局环境或依赖真实 SDK 才能测试。"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "android-env.ps1"
PHASE_PATTERN = re.compile(
    r"(?:android-probe phase=(?:entered|dot-source-begin|dot-source-ready|"
    r"location-begin|location-ready|fixture-ready|child-call-begin|child-call-ready|"
    r"body-begin|body-finished|result-write-begin|result-write-ready)|"
    r"android-process phase=(?:start-info-begin|start-info-ready|child-start-begin|"
    r"child-started|child-wait-begin|child-exited|timed-out|output-completed|disposed))"
    r" elapsed_ms=\d+"
)


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def probe_phase_lines(output: str | bytes | None) -> list[str]:
    """只允许固定阶段标记进入诊断，不转储命令、环境或子进程正文。"""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    return [line for line in (output or "").splitlines() if PHASE_PATTERN.fullmatch(line)]


def run_probe(source: str, *, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("动态测试需要 PowerShell 7，不要求 Android SDK 或 JDK 安装")
    probe = (
        "[Console]::Error.WriteLine('android-probe phase=entered elapsed_ms=0');"
        "[Console]::Error.Flush();"
        "$probeClock=[Diagnostics.Stopwatch]::StartNew();"
        "function Write-AndroidProbePhase([string]$Phase) {"
        "[Console]::Error.WriteLine(\"android-probe phase=$Phase elapsed_ms=$($probeClock.ElapsedMilliseconds)\");"
        "[Console]::Error.Flush() };"
        "$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        "Write-AndroidProbePhase 'dot-source-begin';"
        f". {powershell_literal(str(SCRIPT))};"
        "Write-AndroidProbePhase 'dot-source-ready';"
        "Write-AndroidProbePhase 'body-begin';"
        f"try {{ {source} }} finally {{ Write-AndroidProbePhase 'body-finished' }}"
    )
    started = time.monotonic()
    print("android-probe phase=launch-begin elapsed_ms=0", file=sys.stderr, flush=True)
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", probe],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
            # 官方要求在 PowerShell 启动前退出遥测；只隔离fixture子进程，
            # 不让测试依赖无关 SDK/标识缓存初始化，也不修改父进程或生产配置。
            env={**os.environ, "PYTHONUTF8": "1", "POWERSHELL_TELEMETRY_OPTOUT": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        phases = probe_phase_lines(error.stderr)
        summary = "\n".join(phases) if phases else "no PowerShell phase observed"
        # 不回退为成功、不重试或延长时限；固定诊断替代含整条脚本的异常正文。
        raise AssertionError(
            f"PowerShell probe exceeded {timeout:g}s; elapsed_ms={elapsed_ms}\n{summary}"
        ) from None
    elapsed_ms = int((time.monotonic() - started) * 1000)
    for phase in probe_phase_lines(result.stderr):
        print(phase, file=sys.stderr, flush=True)
    print(
        f"android-probe phase=process-completed elapsed_ms={elapsed_ms} exit_code={result.returncode}",
        file=sys.stderr,
        flush=True,
    )
    return result


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
        Write-AndroidProbePhase 'location-begin';
        Set-Location -LiteralPath {powershell_literal(str(tmp_path))};
        Write-AndroidProbePhase 'location-ready';
        $layout = @{{JdkHome='fixture-jdk'; SdkRoot='fixture-sdk'; GradleUserHome='fixture-cache'}};
        $before = @{{PATH=$env:PATH; JAVA_HOME=$env:JAVA_HOME; ANDROID_HOME=$env:ANDROID_HOME;
            ANDROID_SDK_ROOT=$env:ANDROID_SDK_ROOT; GRADLE_USER_HOME=$env:GRADLE_USER_HOME}};
        $payload = 'import json,os,sys;print(json.dumps({{"args":sys.argv[1:],"java":os.environ["JAVA_HOME"],"sdk":os.environ["ANDROID_HOME"],"sdkRoot":os.environ["ANDROID_SDK_ROOT"],"cache":os.environ["GRADLE_USER_HOME"],"cwd":os.getcwd()}},ensure_ascii=False))';
        Write-AndroidProbePhase 'fixture-ready';
        Write-AndroidProbePhase 'child-call-begin';
        $code = Invoke-AndroidProcess {powershell_literal(sys.executable)} `
            (@('-I', '-S', '-X', 'utf8', '-c', $payload) + @({native_arguments})) $layout 5 -TracePhases;
        Write-AndroidProbePhase 'child-call-ready';
        if ($code -ne 0) {{ throw "fixture child exit code: $code" }};
        foreach($name in $before.Keys) {{
            if([Environment]::GetEnvironmentVariable($name,'Process') -cne $before[$name]) {{
                throw "父进程变量发生改变：$name"
            }}
        }};
    """
    result = run_probe(source)
    assert result.returncode == 0, result.stderr
    phases = probe_phase_lines(result.stderr)
    assert any("phase=child-started " in phase for phase in phases)
    assert any("phase=output-completed " in phase for phase in phases)
    payload = json.loads(result.stdout)
    assert payload == {
        "args": arguments,
        "java": "fixture-jdk",
        "sdk": "fixture-sdk",
        "sdkRoot": "fixture-sdk",
        "cache": "fixture-cache",
        "cwd": str(tmp_path),
    }


def test_probe_timeout_preserves_limit_and_reports_only_safe_phases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorded: dict[str, object] = {}
    monkeypatch.setattr(shutil, "which", lambda _name: "fixture-pwsh")

    def expire(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded.update(kwargs)
        raise subprocess.TimeoutExpired(
            args,
            kwargs["timeout"],
            output=b"token=never-log-tool-output",
            stderr=b"android-probe phase=entered elapsed_ms=0\n"
            b"android-probe phase=dot-source-begin elapsed_ms=12\n"
            b"JAVA_HOME=never-log-path\n"
            b"android-probe phase=never-log-secret elapsed_ms=13\n",
        )

    monkeypatch.setattr(subprocess, "run", expire)
    with pytest.raises(AssertionError) as failure:
        run_probe("throw 'never-log-script-body'")
    assert recorded["timeout"] == 10
    assert recorded["stdin"] == subprocess.DEVNULL
    message = str(failure.value)
    assert "PowerShell probe exceeded 10s" in message
    assert "phase=dot-source-begin elapsed_ms=12" in message
    assert "never-log" not in message
    assert "never-log" not in capsys.readouterr().err


def test_probe_phase_filter_ignores_tool_output_and_partial_lines() -> None:
    assert probe_phase_lines(
        "android-process phase=child-started elapsed_ms=7\n"
        "android-process phase=child-started elapsed_ms=7 bearer=secret\n"
        "\x1b[31mJAVA_HOME=private\n"
        "android-probe phase=dot-source-ready elapsed_ms=12\n"
        "android-probe phase=child-call-ready elapsed_ms="
    ) == [
        "android-process phase=child-started elapsed_ms=7",
        "android-probe phase=dot-source-ready elapsed_ms=12",
    ]


def test_probe_telemetry_optout_is_child_only_and_preserves_parent_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POWERSHELL_TELEMETRY_OPTOUT", "parent-value")
    monkeypatch.setenv("PYTHONUTF8", "parent-utf8-value")
    monkeypatch.setattr(shutil, "which", lambda _name: "fixture-pwsh")
    parent_environment = dict(os.environ)
    recorded: dict[str, object] = {}

    def complete(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", complete)
    result = run_probe("exit 0")
    assert result.returncode == 0
    assert recorded["timeout"] == 10
    child_environment = recorded["env"]
    assert isinstance(child_environment, dict)
    assert child_environment["POWERSHELL_TELEMETRY_OPTOUT"] == "1"
    assert child_environment["PYTHONUTF8"] == "1"
    assert child_environment == {
        **parent_environment,
        "PYTHONUTF8": "1",
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
    }
    assert dict(os.environ) == parent_environment


@pytest.mark.parametrize(
    "source,expected_exit",
    [("exit 7", 7), ("throw 'controlled fixture failure'", 1)],
)
def test_probe_finally_records_completion_without_masking_exit_or_failure(
    source: str, expected_exit: int
) -> None:
    result = run_probe(source)
    assert result.returncode == expected_exit, result.stderr
    phases = probe_phase_lines(result.stderr)
    assert any("phase=body-begin " in phase for phase in phases)
    assert any("phase=body-finished " in phase for phase in phases)
    assert result.stdout == ""


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
        "catch { Write-AndroidProbePhase 'result-write-begin'; Write-Output 'rejected'; "
        "Write-AndroidProbePhase 'result-write-ready'; exit 0 }; exit 4"
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
    assert any(
        line.strip() and PHASE_PATTERN.fullmatch(line) is None
        for line in result.stderr.splitlines()
    ), "应显示缺失工具错误，不能用探针阶段日志冒充真实错误"


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
    assert "android-process phase=" not in result.stderr, "生产调用默认不输出阶段诊断"


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
