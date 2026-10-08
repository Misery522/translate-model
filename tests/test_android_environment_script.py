"""项目专用 Android 启动器不能更改全局环境或依赖真实 SDK 才能测试。"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from itertools import islice
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
PROC_READ_BYTES = 2048
PROC_THREAD_LIMIT = 32
PROC_DIAGNOSTIC_SECONDS = 0.2
PROBE_CLEANUP_SECONDS = 0.5
WAIT_CATEGORIES = ("futex", "pipe", "poll", "wait", "sleep", "io", "unknown")


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def probe_phase_lines(output: str | bytes | None) -> list[str]:
    """只允许固定阶段标记进入诊断，不转储命令、环境或子进程正文。"""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    return [line for line in (output or "").splitlines() if PHASE_PATTERN.fullmatch(line)]


def parse_probe_stat(contents: str) -> tuple[str, int, int]:
    """仅解析 Linux stat 的固定状态、CPU ticks 和线程数，不返回 comm。"""
    _, separator, suffix = contents.rpartition(")")
    fields = suffix.split()
    if not separator or len(fields) < 18 or fields[0] not in set("RSDZTtWXxKPI"):
        raise ValueError("invalid proc stat")
    numbers = [fields[index] for index in (11, 12, 17)]
    if any(re.fullmatch(r"[0-9]{1,20}", value) is None for value in numbers):
        raise ValueError("invalid proc counts")
    user_ticks, system_ticks, threads = map(int, numbers)
    return fields[0], user_ticks + system_ticks, threads


def probe_wait_category(contents: str) -> str:
    """内核符号只分类，不把原符号、路径或任意文本写入日志。"""
    symbol = contents.strip().lower()
    if re.fullmatch(r"[a-z0-9_]{1,80}", symbol) is None:
        return "unknown"
    for category, fragments in (
        ("futex", ("futex",)),
        ("pipe", ("pipe",)),
        ("poll", ("poll", "epoll", "select")),
        ("sleep", ("sleep", "hrtimer")),
        ("io", ("io_schedule", "folio_wait", "page_wait", "filemap")),
        ("wait", ("wait",)),
    ):
        if any(fragment in symbol for fragment in fragments):
            return category
    return "unknown"


def read_probe_proc_file(path: Path) -> str:
    with path.open("rb") as stream:
        return stream.read(PROC_READ_BYTES).decode("ascii", errors="replace")


def probe_process_snapshot(pid: int, *, proc_root: Path = Path("/proc")) -> list[str]:
    """只读本次子进程；采样异常或超预算不能拖住原来的失败处理。"""
    if not sys.platform.startswith("linux"):
        return ["android-probe proc=unsupported"]
    if type(pid) is not int or pid <= 0:
        return ["android-probe proc=unavailable"]
    finished = threading.Event()
    cancelled = threading.Event()
    result: list[str] = []

    def collect() -> None:
        try:
            process_dir = proc_root / str(pid)
            state, cpu_ticks, threads = parse_probe_stat(read_probe_proc_file(process_dir / "stat"))
            waits: Counter[str] = Counter()
            sampled = 0
            for thread_dir in islice((process_dir / "task").iterdir(), PROC_THREAD_LIMIT):
                if cancelled.is_set():
                    return
                if re.fullmatch(r"[0-9]+", thread_dir.name) is None:
                    continue
                sampled += 1
                try:
                    waits[probe_wait_category(read_probe_proc_file(thread_dir / "wchan"))] += 1
                except OSError:
                    waits["unknown"] += 1
            if not cancelled.is_set():
                result.extend(
                    [
                        f"android-probe proc state={state} cpu_ticks={cpu_ticks} threads={threads}",
                        "android-probe thread_waits "
                        + " ".join(f"{category}={waits[category]}" for category in WAIT_CATEGORIES)
                        + f" sampled={sampled}",
                    ]
                )
        except Exception:
            # 诊断本身出错只能标记 unavailable，不得泄露异常正文或覆盖原超时。
            result.append("android-probe proc=unavailable")
        finally:
            finished.set()

    worker = threading.Thread(target=collect, daemon=True, name="android-probe-snapshot")
    try:
        worker.start()
    except RuntimeError:
        return ["android-probe proc=unavailable"]
    if not finished.wait(PROC_DIAGNOSTIC_SECONDS):
        cancelled.set()
        return ["android-probe proc=budget-exhausted"]
    return result


def close_probe_pipes(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def cleanup_probe_process(process: subprocess.Popen[str]) -> str:
    """只清理自己创建的 Popen；kill、通信和管道关闭共享 500ms 回收预算。"""
    finished = threading.Event()
    outcome = ["android-probe cleanup=unavailable"]
    deadline = time.monotonic() + PROBE_CLEANUP_SECONDS

    def cleanup() -> None:
        try:
            if process.poll() is None:
                process.kill()
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0:
                outcome[0] = "android-probe cleanup=budget-exhausted"
                return
            process.communicate(timeout=remaining)
            outcome[0] = "android-probe cleanup=completed"
        except subprocess.TimeoutExpired:
            outcome[0] = "android-probe cleanup=budget-exhausted"
        except Exception:
            outcome[0] = "android-probe cleanup=unavailable"
        finally:
            try:
                # Windows 的 reader thread 可能仍持有锁，关闭也留在有界 daemon 内。
                close_probe_pipes(process)
            except Exception:
                outcome[0] = "android-probe cleanup=unavailable"
            finished.set()

    worker = threading.Thread(target=cleanup, daemon=True, name="android-probe-cleanup")
    try:
        worker.start()
    except RuntimeError:
        return "android-probe cleanup=unavailable"
    if not finished.wait(max(0.0, deadline - time.monotonic())):
        return "android-probe cleanup=budget-exhausted"
    return outcome[0]


def run_probe(source: str, *, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("动态测试需要 PowerShell 7，不要求 Android SDK 或 JDK 安装")
    probe = (
        "[Console]::Error.WriteLine('android-probe phase=entered elapsed_ms=0');"
        "[Console]::Error.Flush();"
        "$probeClock=[Diagnostics.Stopwatch]::StartNew();"
        "function Write-AndroidProbePhase([string]$Phase) {"
        '[Console]::Error.WriteLine("android-probe phase=$Phase elapsed_ms=$($probeClock.ElapsedMilliseconds)");'
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
        process = subprocess.Popen(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", probe],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            # 官方要求在 PowerShell 启动前退出遥测；只隔离fixture子进程，
            # 不让测试依赖无关 SDK/标识缓存初始化，也不修改父进程或生产配置。
            env={**os.environ, "PYTHONUTF8": "1", "POWERSHELL_TELEMETRY_OPTOUT": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError:
        raise AssertionError("PowerShell probe could not start") from None
    elapsed_ms = int((time.monotonic() - started) * 1000)
    print(f"android-probe phase=spawned elapsed_ms={elapsed_ms}", file=sys.stderr, flush=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        phases = probe_phase_lines(error.stderr)
        summary = "\n".join(phases) if phases else "no PowerShell phase observed"
        try:
            returncode = process.poll()
            process_state = "alive" if returncode is None else f"exited exit_code={returncode}"
            snapshot = probe_process_snapshot(process.pid) if returncode is None else []
        except OSError:
            process_state = "unavailable"
            snapshot = ["android-probe proc=unavailable"]
        cleanup = cleanup_probe_process(process)
        # 不回退为成功、不重试或延长时限；固定诊断替代含整条脚本的异常正文。
        raise AssertionError(
            f"PowerShell probe exceeded {timeout:g}s; elapsed_ms={elapsed_ms}\n{summary}\n"
            f"android-probe process={process_state}\n" + "\n".join([*snapshot, cleanup])
        ) from None
    except BaseException:
        cleanup_probe_process(process)
        raise
    close_probe_pipes(process)
    result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
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
        jdk / "release": 'JAVA_VERSION="21.0.12.1"\nJAVA_RUNTIME_VERSION="21.0.12.1+1-LTS"\n',
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


class FakeProbeProcess:
    """不启动工具的进程伪件，便于检查诊断和清理路径，而不是绕过真实用例。"""

    def __init__(self, *, timeout_stderr: bytes | None = None) -> None:
        self.args: list[str] = []
        self.pid = 999_999_999
        self.stdout = None
        self.stderr = None
        self.returncode: int | None = None
        self.timeout_stderr = timeout_stderr
        self.communication_timeouts: list[float] = []
        self.kill_count = 0

    def communicate(self, *, timeout: float) -> tuple[str, str]:
        self.communication_timeouts.append(timeout)
        if self.timeout_stderr is not None and not self.kill_count:
            raise subprocess.TimeoutExpired(
                self.args,
                timeout,
                output=b"token=never-log-tool-output",
                stderr=self.timeout_stderr,
            )
        if self.returncode is None:
            self.returncode = 0
        return "", ""

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.kill_count += 1
        self.returncode = -9


def fixture_proc_stat(*, name: str = "private-process", state: str = "S", threads: int = 40) -> str:
    fields = [state, *("0" for _ in range(18))]
    fields[11], fields[12], fields[17] = "13", "7", str(threads)
    return f"42 ({name}) " + " ".join(fields)


def test_probe_stat_parser_discards_private_names_and_parentheses() -> None:
    assert parse_probe_stat(fixture_proc_stat(name="secret /path with ) and (")) == (
        "S",
        20,
        40,
    )


@pytest.mark.parametrize(
    "value",
    [
        "secret/path",
        "42 (secret) S 0",
        fixture_proc_stat(state="SECRET"),
        fixture_proc_stat(threads=-1),
        fixture_proc_stat(threads=10**21),
    ],
)
def test_probe_stat_parser_rejects_malformed_or_unbounded_counts(value: str) -> None:
    with pytest.raises(ValueError, match="^invalid proc"):
        parse_probe_stat(value)


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("futex_wait_queue", "futex"),
        ("pipe_read", "pipe"),
        ("ep_poll", "poll"),
        ("do_wait", "wait"),
        ("hrtimer_nanosleep", "sleep"),
        ("folio_wait_bit_common", "io"),
        ("/private/path token=secret", "unknown"),
        ("secret_symbol", "unknown"),
        ("0", "unknown"),
    ],
)
def test_probe_waits_use_only_fixed_categories(symbol: str, expected: str) -> None:
    assert probe_wait_category(symbol) == expected


def test_probe_proc_snapshot_reads_only_owned_fixed_files_and_caps_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    process_dir = tmp_path / "42"
    task_dir = process_dir / "task"
    task_dir.mkdir(parents=True)
    for identifier in range(100, 140):
        (task_dir / str(identifier)).mkdir()
    reads: list[Path] = []

    def read(path: Path) -> str:
        reads.append(path)
        assert path.parent == process_dir or path.parent.parent == task_dir
        assert path.name in {"stat", "wchan"}
        return (
            fixture_proc_stat(name="never-log-comm") if path.name == "stat" else "futex_wait_secret"
        )

    monkeypatch.setattr(sys.modules[__name__], "read_probe_proc_file", read)
    result = probe_process_snapshot(42, proc_root=tmp_path)
    assert result[0] == "android-probe proc state=S cpu_ticks=20 threads=40"
    assert "futex=32" in result[1]
    assert "sampled=32" in result[1]
    assert len(reads) == 33
    assert "secret" not in "\n".join(result)
    assert "never-log" not in "\n".join(result)
    assert str(tmp_path) not in "\n".join(result)


def test_probe_proc_file_read_is_limited_to_two_kib(tmp_path: Path) -> None:
    path = tmp_path / "stat"
    path.write_bytes(b"a" * (PROC_READ_BYTES + 200))
    assert read_probe_proc_file(path) == "a" * PROC_READ_BYTES


def test_probe_proc_error_is_safe_and_does_not_mask_original_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    def fail(_path: Path) -> str:
        raise OSError("never-log-private-path")

    monkeypatch.setattr(sys.modules[__name__], "read_probe_proc_file", fail)
    assert probe_process_snapshot(42) == ["android-probe proc=unavailable"]


def test_probe_proc_diagnostic_budget_does_not_wait_for_blocked_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    thread_dir = tmp_path / "42" / "task" / "43"
    thread_dir.mkdir(parents=True)
    release = threading.Event()
    reader_done = threading.Event()
    reads: list[Path] = []

    def block(path: Path) -> str:
        reads.append(path)
        try:
            release.wait(timeout=2)
            return fixture_proc_stat()
        finally:
            reader_done.set()

    monkeypatch.setattr(sys.modules[__name__], "read_probe_proc_file", block)
    started = time.monotonic()
    try:
        assert probe_process_snapshot(42, proc_root=tmp_path) == [
            "android-probe proc=budget-exhausted"
        ]
        assert time.monotonic() - started < 0.8
    finally:
        release.set()
        assert reader_done.wait(timeout=1)
    assert len(reads) == 1


def test_probe_cleanup_kills_only_the_supplied_process_and_preserves_bound() -> None:
    process = FakeProbeProcess()
    unrelated = FakeProbeProcess()
    assert cleanup_probe_process(process) == "android-probe cleanup=completed"
    assert process.kill_count == 1
    assert unrelated.kill_count == 0
    assert len(process.communication_timeouts) == 1
    assert 0 < process.communication_timeouts[0] <= PROBE_CLEANUP_SECONDS


def test_probe_cleanup_budget_does_not_wait_for_blocked_pipe_close() -> None:
    process = FakeProbeProcess()
    release = threading.Event()
    closed = threading.Event()

    class BlockedStream:
        def close(self) -> None:
            release.wait(timeout=2)
            closed.set()

    process.stdout = BlockedStream()
    started = time.monotonic()
    try:
        assert cleanup_probe_process(process) == "android-probe cleanup=budget-exhausted"
        assert time.monotonic() - started < 0.8
        assert process.kill_count == 1
    finally:
        release.set()
        assert closed.wait(timeout=1)


def test_probe_cleanup_budget_does_not_wait_for_stuck_communication() -> None:
    process = FakeProbeProcess()
    release = threading.Event()
    finished = threading.Event()

    def communicate(*, timeout: float) -> tuple[str, str]:
        process.communication_timeouts.append(timeout)
        try:
            release.wait(timeout=2)
            return "", ""
        finally:
            finished.set()

    process.communicate = communicate
    started = time.monotonic()
    try:
        assert cleanup_probe_process(process) == "android-probe cleanup=budget-exhausted"
        assert time.monotonic() - started < 0.8
        assert process.kill_count == 1
        assert 0 < process.communication_timeouts[0] <= PROBE_CLEANUP_SECONDS
    finally:
        release.set()
        assert finished.wait(timeout=1)


def test_probe_cleanup_errors_are_controlled_not_exception_dumps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProbeProcess()

    def fail() -> None:
        raise OSError("never-log-path-or-token")

    monkeypatch.setattr(process, "kill", fail)
    assert cleanup_probe_process(process) == "android-probe cleanup=unavailable"


def test_probe_spawn_errors_remain_failures_without_private_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "fixture-pwsh")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("never-log-private-executable")

    monkeypatch.setattr(subprocess, "Popen", fail)
    with pytest.raises(AssertionError, match="^PowerShell probe could not start$"):
        run_probe("exit 0")


def test_probe_timeout_preserves_limit_and_reports_only_safe_phases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorded: dict[str, object] = {}
    monkeypatch.setattr(shutil, "which", lambda _name: "fixture-pwsh")

    process = FakeProbeProcess(
        timeout_stderr=b"android-probe phase=entered elapsed_ms=0\n"
        b"android-probe phase=dot-source-begin elapsed_ms=12\n"
        b"JAVA_HOME=never-log-path\n"
        b"android-probe phase=never-log-secret elapsed_ms=13\n"
    )

    def create(args: list[str], **kwargs: object) -> FakeProbeProcess:
        process.args = args
        recorded.update(kwargs)
        return process

    monkeypatch.setattr(subprocess, "Popen", create)
    monkeypatch.setattr(
        sys.modules[__name__],
        "probe_process_snapshot",
        lambda _pid: ["android-probe proc=unavailable"],
    )
    with pytest.raises(AssertionError) as failure:
        run_probe("throw 'never-log-script-body'")
    assert process.communication_timeouts[0] == 10
    assert 0 < process.communication_timeouts[1] <= PROBE_CLEANUP_SECONDS
    assert process.kill_count == 1
    assert recorded["stdin"] == subprocess.DEVNULL
    message = str(failure.value)
    assert "PowerShell probe exceeded 10s" in message
    assert "phase=dot-source-begin elapsed_ms=12" in message
    assert "android-probe process=alive" in message
    assert "android-probe cleanup=completed" in message
    assert "never-log" not in message
    assert "never-log" not in capsys.readouterr().err


def test_probe_timeout_after_exit_does_not_inspect_proc_or_claim_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "fixture-pwsh")
    process = FakeProbeProcess(timeout_stderr=b"")
    process.returncode = 0
    inspected: list[int] = []

    def snapshot(pid: int) -> list[str]:
        inspected.append(pid)
        return ["android-probe proc=unavailable"]

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(sys.modules[__name__], "probe_process_snapshot", snapshot)
    with pytest.raises(AssertionError) as failure:
        run_probe("exit 0")
    assert inspected == []
    assert process.kill_count == 0
    assert process.communication_timeouts[0] == 10
    assert "android-probe process=exited exit_code=0" in str(failure.value)


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
    process = FakeProbeProcess()

    def complete(args: list[str], **kwargs: object) -> FakeProbeProcess:
        process.args = args
        recorded.update(kwargs)
        return process

    monkeypatch.setattr(subprocess, "Popen", complete)
    result = run_probe("exit 0")
    assert result.returncode == 0
    assert process.communication_timeouts == [10]
    assert process.kill_count == 0
    child_environment = recorded["env"]
    assert isinstance(child_environment, dict)
    assert child_environment["POWERSHELL_TELEMETRY_OPTOUT"] == "1"
    assert child_environment["PYTHONUTF8"] == "1"
    child_matches_expected = child_environment == {
        **parent_environment,
        "PYTHONUTF8": "1",
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
    }
    assert child_matches_expected, "子进程只能覆盖明确指定的两个变量"
    parent_is_unchanged = dict(os.environ) == parent_environment
    assert parent_is_unchanged, "父进程环境必须保持完整原值，不转储环境内容"


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
def test_missing_toolchain_parts_fail_clearly(tmp_path: Path, missing: str, label: str) -> None:
    result = run_probe(probe_toolchain(tmp_path, fixture_toolchain(tmp_path, missing)))
    assert result.returncode == 0, result.stderr
    assert label in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows 工具布局模拟，不要求真实 SDK 安装")
@pytest.mark.parametrize(
    "relative,content,label",
    [
        ("jdk/release", 'JAVA_VERSION="25.0.2"\n', "JDK 版本不是已锁定"),
        ("sdk/cmdline-tools/22.0/source.properties", "Pkg.Revision=23.0\n", "固定版本 22.0"),
        (
            "sdk/platforms/android-36/source.properties",
            "AndroidVersion.ApiLevel=37\n",
            "不会把 API 37",
        ),
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
