"""CI 整套测试入口必须限时、无缓冲，且诊断不得泄露失败命令。"""

from __future__ import annotations

import ast
import builtins
import re
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def unit_test_command() -> list[str]:
    """读取唯一测试步骤，保留 Bash 与 PowerShell 通用的多行引号边界。"""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    header = "      - name: Unit tests (hard limit of 60 seconds)"
    assert lines.count(header) == 1
    start = lines.index(header) + 1
    assert lines[start] == "        run: |"
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("          "):
            break
        body.append(line[10:])
    return shlex.split("\n".join(body))


def unit_test_program() -> ast.Module:
    command = unit_test_command()
    assert len(command) == 7
    assert command[:6] == ["uv", "run", "--no-sync", "python", "-u", "-c"]
    return ast.parse(command[-1])


def run_unit_test_program(result: int | Exception) -> tuple[list[str], dict[str, object]]:
    """执行真实入口 AST，但只替换进程与时钟，不启动另一套 pytest。"""
    seen: dict[str, object] = {}
    output: list[str] = []
    clock = iter((10.0, 10.025, 10.050))

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["command"] = command
        seen["options"] = kwargs
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(command, result)

    def exit_process(code: int) -> None:
        raise SystemExit(code)

    def print_marker(value: str, *, flush: bool = False) -> None:
        assert flush is True
        output.append(value)

    modules = {
        "subprocess": SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired),
        "sys": SimpleNamespace(executable="/private/python-path", exit=exit_process),
        "time": SimpleNamespace(monotonic=lambda: next(clock)),
    }

    def import_module(name: str, *args: object, **kwargs: object) -> object:
        assert name in modules
        return modules[name]

    namespace = {"__builtins__": dict(vars(builtins), __import__=import_module, print=print_marker)}
    with pytest.raises(SystemExit) as caught:
        exec(compile(unit_test_program(), "<ci-unit-entry>", "exec"), namespace)
    seen["exit_code"] = caught.value.code
    return output, seen


def test_ci_unit_entry_has_one_limited_unbuffered_child() -> None:
    tree = unit_test_program()
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    runs = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "run"
    ]
    assert len(runs) == 1
    assert {item.arg: ast.literal_eval(item.value) for item in runs[0].keywords} == {"timeout": 60}
    output, seen = run_unit_test_program(0)
    assert seen["command"] == ["/private/python-path", "-u", "-m", "pytest", "-m", "not ollama"]
    assert seen["options"] == {"timeout": 60}
    assert output[0] == "ci-suite phase=launch elapsed_ms=0 limit_s=60"


@pytest.mark.parametrize("code", (0, 1, 2, 3, 4, 5, 7, 124, 125))
def test_ci_unit_entry_propagates_pytest_exit_code(code: int) -> None:
    output, seen = run_unit_test_program(code)
    assert seen["exit_code"] == code
    assert output[-1] == f"ci-suite phase=exit elapsed_ms=25 exit_code={code}"
    assert len(output) == 2


@pytest.mark.parametrize(
    ("error", "phase", "code"),
    (
        (
            subprocess.TimeoutExpired(
                ["/private/command", "secret-token"],
                60,
                output="secret-source",
                stderr="secret-error",
            ),
            "timeout",
            124,
        ),
        (OSError("/private/path secret-token secret-source"), "process-error", 125),
    ),
)
def test_ci_unit_entry_reports_fixed_failure_without_exception_dump(
    error: Exception, phase: str, code: int
) -> None:
    output, seen = run_unit_test_program(error)
    assert seen["exit_code"] == code
    assert output[1] == f"ci-suite phase={phase} elapsed_ms=25"
    assert output[-1] == f"ci-suite phase=exit elapsed_ms=50 exit_code={code}"
    assert len(output) == 3
    assert all(
        re.fullmatch(
            r"ci-suite phase=(?:launch|timeout|process-error|exit) elapsed_ms=\d+"
            r"(?: limit_s=60| exit_code=\d+)?",
            line,
        )
        for line in output
    )
    assert "secret" not in "\n".join(output)
    assert "/private" not in "\n".join(output)
