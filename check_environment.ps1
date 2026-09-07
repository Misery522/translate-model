param(
    [switch]$RequireOllama,
    [string]$PythonPath,
    [string]$Model,
    [string]$OllamaBaseUrl,
    [string]$ExpectedModelRoot,
    [ValidateRange(1, 30)]
    [int]$TimeoutSec = 5
)

# Read-only diagnostics. No environment, permissions, files, or processes are changed.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $PythonPath) {
    $PythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
}
if (-not $Model) {
    $Model = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { 'qwen3.5:4b' }
}
if (-not $OllamaBaseUrl) {
    $OllamaBaseUrl = if ($env:OLLAMA_BASE_URL) {
        $env:OLLAMA_BASE_URL
    } else {
        'http://127.0.0.1:11434'
    }
}

$results = [System.Collections.Generic.List[object]]::new()
$failures = [System.Collections.Generic.List[string]]::new()

function Add-CheckResult {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail,
        [bool]$Required = $true
    )
    $status = if ($Passed) { 'PASS' } elseif ($Required) { 'FAIL' } else { 'PENDING' }
    $results.Add([pscustomobject]@{ Status = $status; Check = $Name; Detail = $Detail })
    if (-not $Passed -and $Required) {
        $failures.Add($Name)
    }
}

$pythonReady = Test-Path -LiteralPath $PythonPath -PathType Leaf
Add-CheckResult 'Project Python' $pythonReady 'Use -PythonPath to select an existing interpreter.'
if ($pythonReady) {
    $pythonVersion = (& $PythonPath -B --version 2>&1 | Out-String).Trim()
    Add-CheckResult 'Python version' ($LASTEXITCODE -eq 0) $pythonVersion

    $null = & $PythonPath -B -m pip check 2>&1
    Add-CheckResult 'pip dependency check' ($LASTEXITCODE -eq 0) 'Run python -m pip check for details.'

    $null = & $PythonPath -B -c 'import gradio, langchain_ollama, langgraph, ollama' 2>&1
    Add-CheckResult 'Application imports' ($LASTEXITCODE -eq 0) 'Gradio and model workflow dependencies.'

    # Keep URL validation identical to the app. Disable redirects and proxy inheritance.
    # Report only fixed status flags; never echo exception bodies or input credentials.
    $probeCode = @'
import json
import sys

sys.path.insert(0, sys.argv[1])
try:
    import httpx
    from translation_agent import validate_local_ollama_base_url
    address = validate_local_ollama_base_url(sys.argv[2])
except Exception:
    print(json.dumps({"valid_address": False, "online": False, "model_present": False}))
    sys.exit(0)

result = {"valid_address": True, "online": False, "model_present": False}
try:
    with httpx.Client(timeout=float(sys.argv[4]), trust_env=False, follow_redirects=False) as client:
        version = client.get(address + "/api/version")
        version.raise_for_status()
        version_data = version.json()
        if not isinstance(version_data, dict) or not isinstance(version_data.get("version"), str):
            raise ValueError("Invalid version response")
        tags = client.get(address + "/api/tags")
        tags.raise_for_status()
        models = tags.json().get("models")
        if not isinstance(models, list):
            raise ValueError("Invalid model list")
        result["online"] = True
        result["model_present"] = any(
            isinstance(item, dict) and item.get("name") == sys.argv[3] for item in models
        )
except Exception:
    pass
print(json.dumps(result))
'@
    try {
        $probeOutput = & $PythonPath -B -c $probeCode $PSScriptRoot $OllamaBaseUrl $Model $TimeoutSec 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'Probe failed' }
        $probe = ($probeOutput | Out-String) | ConvertFrom-Json
        Add-CheckResult 'Ollama address' $probe.valid_address 'Only bare loopback HTTP(S) addresses are allowed.'
        Add-CheckResult 'Ollama local API' $probe.online 'Read-only /api/version and /api/tags checks.' $RequireOllama
        Add-CheckResult 'Installed model' $probe.model_present 'Checked against the selected model name.' $RequireOllama
    } catch {
        Add-CheckResult 'Ollama diagnostic' $false 'Probe unavailable; verify application dependencies.'
    }
}

$configuredModelRoot = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'Process')
if (-not $configuredModelRoot) {
    $configuredModelRoot = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
}
if ($ExpectedModelRoot) {
    $directoryExists = Test-Path -LiteralPath $ExpectedModelRoot -PathType Container
    Add-CheckResult 'Expected model directory' $directoryExists 'Existence only; this does not prove the running service uses it.' $RequireOllama
    $matches = $configuredModelRoot -eq $ExpectedModelRoot
    Add-CheckResult 'Expected directory configuration' $matches 'Checks inherited/user configuration, not the service process environment.' $false
} else {
    Add-CheckResult 'Model directory configuration' $true 'Custom OLLAMA_MODELS is optional; disk paths are not returned by the API.'
}

$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
Add-CheckResult 'Ollama CLI' ($null -ne $ollamaCommand) 'Optional when the local API is available.' $false
$codeCommand = Get-Command code -ErrorAction SilentlyContinue
Add-CheckResult 'VS Code CLI' ($null -ne $codeCommand) 'Optional editor integration.' $false
$results | Format-Table -AutoSize -Wrap
if ($failures.Count -gt 0) {
    Write-Host "Required checks failed: $($failures -join ', ')"
    exit 1
}
Write-Host 'Environment checks passed.'
exit 0
