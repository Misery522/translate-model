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
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.Environment['RUST_BACKTRACE'] = '1'
foreach ($argument in @('test', '--locked', '--', '--nocapture', '--test-threads=1')) {
    $startInfo.ArgumentList.Add($argument)
}

# CI 已用 --no-run 完成编译。这里只约束测试执行，且只管理本脚本启动的进程树。
$testProcess = [System.Diagnostics.Process]::new()
$testProcess.StartInfo = $startInfo
try {
    if (-not $testProcess.Start()) { throw '无法启动 Rust 测试进程。' }

    # 必须同时异步读取两个管道，避免任一缓冲区写满后让测试进程互相等待。
    $standardOutputTask = $testProcess.StandardOutput.ReadToEndAsync()
    $standardErrorTask = $testProcess.StandardError.ReadToEndAsync()

    if (-not $testProcess.WaitForExit($TimeoutSeconds * 1000)) {
        try { $testProcess.Kill($true) } catch [System.InvalidOperationException] {
            # 刚好自然结束时无需再终止。
        }
        [void]$testProcess.WaitForExit(5000)
        $standardOutput = $standardOutputTask.GetAwaiter().GetResult()
        $standardError = $standardErrorTask.GetAwaiter().GetResult()
        if ($standardOutput) { [Console]::Out.Write($standardOutput) }
        if ($standardError) { [Console]::Error.Write($standardError) }
        Write-Output "Rust 测试超过 $TimeoutSeconds 秒上限；本次测试进程树已停止。"
        exit 124
    }

    # 无参 WaitForExit 确保进程结束事件与异步输出读取全部排空后再取退出码。
    $testProcess.WaitForExit()
    $standardOutput = $standardOutputTask.GetAwaiter().GetResult()
    $standardError = $standardErrorTask.GetAwaiter().GetResult()
    if ($standardOutput) { [Console]::Out.Write($standardOutput) }
    if ($standardError) { [Console]::Error.Write($standardError) }
    $exitCode = $testProcess.ExitCode
    exit $exitCode
} finally {
    $testProcess.Dispose()
}
