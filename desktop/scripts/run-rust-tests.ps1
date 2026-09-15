[CmdletBinding()]
param(
    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 60,

    # 仅供本仓库回归测试使用。生产和 CI 不传入该参数，始终执行固定的 cargo test。
    [ValidateSet('', 'capture', 'failure', 'timeout', 'sensitive')]
    [string]$TestMode = '',

    [string]$TestStatePath = ''
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

function Get-SensitiveEnvironmentValues {
    $sensitiveNamePattern = '(?i)(?:^|_)(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY|PRIVATE_KEY|AUTHORIZATION|COOKIE|CREDENTIAL|JWT)(?:$|_)'
    $values = foreach ($entry in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
        if (
            [string]$entry.Key -match $sensitiveNamePattern -and
            -not [string]::IsNullOrEmpty([string]$entry.Value) -and
            ([string]$entry.Value).Length -ge 4
        ) {
            [string]$entry.Value
        }
    }
    @($values | Sort-Object -Unique -CaseSensitive | Sort-Object -Property { $_.Length } -Descending)
}

function Protect-SensitiveOutput {
    param(
        [AllowNull()]
        [string]$Text,
        [string[]]$SensitiveValues
    )

    if ([string]::IsNullOrEmpty($Text)) { return $Text }

    $safeText = $Text
    foreach ($value in $SensitiveValues) {
        # 先替换环境中已知的秘密值，可覆盖没有 key= 前缀的裸值。
        $safeText = $safeText.Replace($value, '[REDACTED]')
    }

    # 认证与 Cookie 头的整个值都属于凭据，不能只遮住 Basic/Bearer 或首个键值段。
    $safeText = [regex]::Replace(
        $safeText,
        '(?im)^(\s*(?:Authorization|Proxy-Authorization|Cookie|Set-Cookie)\s*:\s*)[^\r\n]*',
        '$1[REDACTED]'
    )
    $safeText = [regex]::Replace(
        $safeText,
        '(?i)(\bAuthorization\s*:\s*Bearer\s+)[^\s"'',;]+',
        '$1[REDACTED]'
    )
    $safeText = [regex]::Replace(
        $safeText,
        '(?i)(\b[A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY|PRIVATE_KEY|AUTHORIZATION|COOKIE|CREDENTIAL|JWT)[A-Za-z0-9_]*\b\s*[:=]\s*)(?:"[^"\r\n]*"|''[^''\r\n]*''|[^\s\r\n,;&]+)',
        '$1[REDACTED]'
    )
    $safeText = [regex]::Replace(
        $safeText,
        '(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{4,}',
        '$1[REDACTED]'
    )
    $safeText = [regex]::Replace(
        $safeText,
        '\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b',
        '[REDACTED]'
    )
    $safeText
}

$desktopDirectory = Split-Path -Parent $PSScriptRoot
$startInfo = [System.Diagnostics.ProcessStartInfo]::new()

if ($TestMode) {
    if ($env:YIJING_RUST_RUNNER_SELF_TEST -ne '1') {
        [Console]::Error.WriteLine('测试夹具入口只允许由仓库回归测试显式启用。')
        exit 64
    }
    $fixturePath = Join-Path $PSScriptRoot 'fixtures\rust-runner-fixture.ps1'
    if (-not (Test-Path -LiteralPath $fixturePath -PathType Leaf)) {
        [Console]::Error.WriteLine('找不到 Rust 运行器回归测试夹具。')
        exit 66
    }
    if ($TestMode -eq 'timeout' -and [string]::IsNullOrWhiteSpace($TestStatePath)) {
        [Console]::Error.WriteLine('超时回归测试必须提供状态文件路径。')
        exit 64
    }

    $powerShellExecutable = Join-Path $PSHOME 'pwsh.exe'
    if (-not (Test-Path -LiteralPath $powerShellExecutable -PathType Leaf)) {
        $powerShellExecutable = Join-Path $PSHOME 'pwsh'
    }
    $startInfo.FileName = $powerShellExecutable
    $startInfo.WorkingDirectory = $PSScriptRoot
    foreach ($argument in @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', $fixturePath, '-Mode', $TestMode)) {
        $startInfo.ArgumentList.Add($argument)
    }
    if ($TestStatePath) {
        $startInfo.ArgumentList.Add('-StatePath')
        $startInfo.ArgumentList.Add($TestStatePath)
    }
} else {
    if ($TestStatePath) {
        [Console]::Error.WriteLine('TestStatePath 只能与受保护的测试夹具入口一起使用。')
        exit 64
    }
    $startInfo.FileName = 'cargo'
    $startInfo.WorkingDirectory = Join-Path $desktopDirectory 'src-tauri'
    foreach ($argument in @('test', '--locked', '--', '--nocapture', '--test-threads=1')) {
        $startInfo.ArgumentList.Add($argument)
    }
}

$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.StandardOutputEncoding = $utf8NoBom
$startInfo.StandardErrorEncoding = $utf8NoBom
$startInfo.Environment['RUST_BACKTRACE'] = '1'
$sensitiveValues = Get-SensitiveEnvironmentValues

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
        if ($standardOutput) { [Console]::Out.Write((Protect-SensitiveOutput $standardOutput $sensitiveValues)) }
        if ($standardError) { [Console]::Error.Write((Protect-SensitiveOutput $standardError $sensitiveValues)) }
        Write-Output "Rust 测试超过 $TimeoutSeconds 秒上限；本次测试进程树已停止。"
        exit 124
    }

    # 无参 WaitForExit 确保进程结束事件与异步输出读取全部排空后再取退出码。
    $testProcess.WaitForExit()
    $standardOutput = $standardOutputTask.GetAwaiter().GetResult()
    $standardError = $standardErrorTask.GetAwaiter().GetResult()
    if ($standardOutput) { [Console]::Out.Write((Protect-SensitiveOutput $standardOutput $sensitiveValues)) }
    if ($standardError) { [Console]::Error.Write((Protect-SensitiveOutput $standardError $sensitiveValues)) }
    $exitCode = $testProcess.ExitCode
    exit $exitCode
} finally {
    $testProcess.Dispose()
}
