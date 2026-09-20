[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('capture', 'failure', 'timeout', 'sensitive')]
    [string]$Mode,

    [string]$StatePath = ''
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

switch ($Mode) {
    'capture' {
        # 两个输出均超过常见管道缓冲区，用于证明父进程会同时排空 stdout/stderr。
        [Console]::Out.Write(('O' * 131072) + "`nCAPTURE_STDOUT_OK`n")
        [Console]::Error.Write(('E' * 131072) + "`nCAPTURE_STDERR_OK`n")
        exit 0
    }
    'failure' {
        [Console]::Out.WriteLine('FAILURE_STDOUT_OK')
        [Console]::Error.WriteLine('FAILURE_STDERR_OK')
        exit 37
    }
    'timeout' {
        if ([string]::IsNullOrWhiteSpace($StatePath)) { exit 64 }
        $childStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $childStartInfo.FileName = (Join-Path $PSHOME 'pwsh.exe')
        if (-not (Test-Path -LiteralPath $childStartInfo.FileName -PathType Leaf)) {
            $childStartInfo.FileName = Join-Path $PSHOME 'pwsh'
        }
        $childStartInfo.UseShellExecute = $false
        $childStartInfo.CreateNoWindow = $true
        foreach ($argument in @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 30')) {
            $childStartInfo.ArgumentList.Add($argument)
        }
        $child = [System.Diagnostics.Process]::Start($childStartInfo)
        [IO.File]::WriteAllText($StatePath, [string]$child.Id, [Text.UTF8Encoding]::new($false))
        [Console]::Out.WriteLine("TIMEOUT_CHILD_STARTED=$($child.Id)")
        Start-Sleep -Seconds 30
        exit 0
    }
    'sensitive' {
        $secretValue = $env:YIJING_TEST_SECRET
        $tokenValue = $env:YIJING_TEST_TOKEN
        [Console]::Out.WriteLine("YIJING_TEST_SECRET=$secretValue")
        [Console]::Out.WriteLine("raw:$secretValue")
        [Console]::Out.WriteLine("raw-token:$tokenValue")
        [Console]::Out.WriteLine('Authorization: Basic dXNlcjpwYXNz')
        [Console]::Out.WriteLine('Cookie: session=abc123; theme=dark; csrf=def456')
        [Console]::Error.WriteLine("Authorization: Bearer $secretValue")
        [Console]::Error.WriteLine('Proxy-Authorization: Digest username="demo", response="digest-value"')
        [Console]::Error.WriteLine('Set-Cookie: session=server456; Path=/; Secure; HttpOnly')
        [Console]::Error.WriteLine("TOKEN=$tokenValue")
        [Console]::Error.WriteLine('github_pat_abcdefghijklmnopqrstuvwxyz0123456789')
        exit 0
    }
}
