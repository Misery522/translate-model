param(
    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'
$desktopDirectory = Split-Path -Parent $PSScriptRoot
$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = 'cargo'
$startInfo.WorkingDirectory = Join-Path $desktopDirectory 'src-tauri'
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
foreach ($argument in @('test', '--locked', '--', '--test-threads=1')) {
    $startInfo.ArgumentList.Add($argument)
}

# CI 已用 --no-run 完成编译。这里只约束测试执行，且只管理本脚本启动的进程树。
$testProcess = [System.Diagnostics.Process]::new()
$testProcess.StartInfo = $startInfo
try {
    if (-not $testProcess.Start()) { throw '无法启动 Rust 测试进程。' }
    if (-not $testProcess.WaitForExit($TimeoutSeconds * 1000)) {
        try { $testProcess.Kill($true) } catch [System.InvalidOperationException] {
            # 刚好自然结束时无需再终止。
        }
        [void]$testProcess.WaitForExit(5000)
        Write-Output 'Rust 测试超过 60 秒上限；本次测试进程树已停止。'
        exit 124
    }
    exit $testProcess.ExitCode
} finally {
    $testProcess.Dispose()
}
