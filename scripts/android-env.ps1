#requires -Version 7.0
<#
.SYNOPSIS
仅为子进程选择译境固定 Android 构建环境。
.DESCRIPTION
不安装工具、不修改全局或父进程环境变量，不通过 cmd 或其他 Shell 执行参数。
doctor 检查完整环境；sdk 和 gradle 只运行各自的固定 Java CLI。
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Position = 0)]
    [ValidateSet('doctor', 'sdk', 'gradle')]
    [string]$Mode = 'doctor',
    [string]$JdkHome,
    [string]$SdkRoot,
    [string]$GradleHome,
    [string]$GradleUserHome,
    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 1200,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ToolArguments = @()
)

function Get-AndroidRequiredFile {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 $Label：$Path。请先安装已批准的固定工具，不会自动改用其他版本。"
    }
    return [IO.Path]::GetFullPath($Path)
}

function Get-AndroidDirectory {
    param([string]$Path, [string]$Label, [switch]$MayNotExist)
    $absolute = [IO.Path]::GetFullPath($Path)
    if (Test-Path -LiteralPath $absolute -PathType Leaf) {
        throw "$Label 应为目录：$absolute"
    }
    if (-not $MayNotExist -and -not (Test-Path -LiteralPath $absolute -PathType Container)) {
        throw "缺少 $Label 目录：$absolute"
    }
    return $absolute
}

function Get-AndroidToolchain {
    param(
        [ValidateSet('doctor', 'sdk', 'gradle')][string]$SelectedMode,
        [string]$SelectedJdkHome,
        [string]$SelectedSdkRoot,
        [string]$SelectedGradleHome,
        [string]$SelectedGradleUserHome
    )
    if (-not $IsWindows) {
        throw '此脚本当前只支持 Windows；跨平台 CI 的源码测试不要求本机安装 Android SDK。'
    }
    $localData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ([string]::IsNullOrWhiteSpace($localData)) {
        throw '无法定位当前用户的 LocalApplicationData，请显式提供工具路径。'
    }
    $toolchainRoot = Join-Path $localData 'Yijing/toolchains'
    if (-not $SelectedJdkHome) {
        $SelectedJdkHome = Join-Path $toolchainRoot 'jdk-21.0.12.1+1'
    }
    if (-not $SelectedSdkRoot) {
        $SelectedSdkRoot = Join-Path $localData 'Android/Sdk'
    }
    if (-not $SelectedGradleHome) {
        $SelectedGradleHome = Join-Path $toolchainRoot 'gradle-8.14.3'
    }
    if (-not $SelectedGradleUserHome) {
        $SelectedGradleUserHome = Join-Path (Split-Path -Parent $PSScriptRoot) 'artifacts/android-gradle-user-home'
    }
    $layout = @{
        JdkHome = Get-AndroidDirectory $SelectedJdkHome 'JDK 21.0.12.1+1'
        SdkRoot = Get-AndroidDirectory $SelectedSdkRoot 'Android SDK'
        GradleUserHome = Get-AndroidDirectory $SelectedGradleUserHome '项目 Gradle 缓存' -MayNotExist
    }
    $layout.Java = Get-AndroidRequiredFile (Join-Path $layout.JdkHome 'bin/java.exe') 'JDK java.exe'
    $layout.Javac = Get-AndroidRequiredFile (Join-Path $layout.JdkHome 'bin/javac.exe') 'JDK javac.exe'
    $release = Get-Content -LiteralPath (Get-AndroidRequiredFile (Join-Path $layout.JdkHome 'release') 'JDK release') -Raw
    if ($release -notmatch '(?m)^JAVA_VERSION="21\.0\.12\.1"\r?$' -or
        $release -notmatch '(?m)^JAVA_RUNTIME_VERSION="21\.0\.12\.1\+1(?:[-"].*)?\r?$') {
        throw 'JDK 版本不是已锁定的 21.0.12.1+1；请显式使用正确目录，不会退回 Android Studio JBR。'
    }
    if ($SelectedMode -in @('doctor', 'sdk')) {
        $cmdtools = Join-Path $layout.SdkRoot 'cmdline-tools/22.0'
        $layout.SdkCommandToolsHome = $cmdtools
        $layout.SdkManagerJar = Get-AndroidRequiredFile (Join-Path $cmdtools 'lib/sdkmanager-classpath.jar') 'SDK 命令行工具 22.0'
        $cmdProperties = Get-Content -LiteralPath (Get-AndroidRequiredFile (Join-Path $cmdtools 'source.properties') '命令行工具版本文件') -Raw
        if ($cmdProperties -notmatch '(?m)^Pkg\.Revision=22\.0(?:\.0)?\r?$') {
            throw 'SDK 命令行工具必须为固定版本 22.0。'
        }
    }
    if ($SelectedMode -in @('doctor', 'gradle')) {
        $layout.GradleHome = Get-AndroidDirectory $SelectedGradleHome 'Gradle 8.14.3'
        $layout.GradleCliJar = Get-AndroidRequiredFile (Join-Path $layout.GradleHome 'lib/gradle-gradle-cli-main-8.14.3.jar') 'Gradle 8.14.3 CLI'
        $layout.GradleInstrumentationAgent = Get-AndroidRequiredFile (Join-Path $layout.GradleHome 'lib/agents/gradle-instrumentation-agent-8.14.3.jar') 'Gradle 8.14.3 instrumentation agent'
        $platform = Join-Path $layout.SdkRoot 'platforms/android-36'
        $null = Get-AndroidRequiredFile (Join-Path $platform 'android.jar') 'SDK Platform 36 android.jar'
        $platformProperties = Get-Content -LiteralPath (Get-AndroidRequiredFile (Join-Path $platform 'source.properties') 'SDK Platform 36 版本文件') -Raw
        if ($platformProperties -notmatch '(?m)^AndroidVersion\.ApiLevel=36(?:\.0)?\r?$') {
            throw 'SDK Platform 36 版本文件不匹配；不会把 API 37 当作替代品。'
        }
        $buildTools = Join-Path $layout.SdkRoot 'build-tools/36.0.0'
        $null = Get-AndroidRequiredFile (Join-Path $buildTools 'aapt2.exe') 'Build Tools 36.0.0'
        $buildProperties = Get-Content -LiteralPath (Get-AndroidRequiredFile (Join-Path $buildTools 'source.properties') 'Build Tools 版本文件') -Raw
        if ($buildProperties -notmatch '(?m)^Pkg\.Revision=36\.0\.0\r?$') {
            throw 'Build Tools 版本文件必须为 36.0.0。'
        }
    }
    return $layout
}

function Get-AndroidJavaArguments {
    param(
        [ValidateSet('sdk', 'gradle')][string]$SelectedMode,
        [hashtable]$Layout,
        [AllowEmptyCollection()][string[]]$Arguments = @()
    )
    if ($SelectedMode -eq 'sdk') {
        foreach ($argument in $Arguments) {
            if ($argument -match '(?i)^--(?:sdk[_-]root|channel|no_https)(?:=|$)') {
                throw 'SDK 根目录、稳定通道和 HTTPS 由启动器固定，不能在 ToolArguments 中覆盖。'
            }
        }
        return @("-Dcom.android.sdklib.toolsdir=$($Layout.SdkCommandToolsHome)",
            '-classpath', $Layout.SdkManagerJar,
            'com.android.sdklib.tool.sdkmanager.SdkManagerCli',
            "--sdk_root=$($Layout.SdkRoot)", '--channel=0') + $Arguments
    }
    foreach ($argument in $Arguments) {
        if ($argument -match '(?i)org\.gradle\.(?:java\.(?:home|installations\.(?:auto-download|auto-detect|paths))|daemon)' -or
            $argument -match '(?i)android\.overridePathCheck' -or
            $argument -match '(?i)^--(?:daemon|foreground|gradle-user-home)(?:=|$)' -or
            $argument -match '(?i)gradle\.user\.home' -or $argument -match '^-g') {
            throw 'Gradle 的 Java、缓存、无常驻进程、禁止自动下载和 Android 路径检查不能在 ToolArguments 中覆盖。'
        }
    }
    # 自动下载由 Gradle project property 控制，只传同名 JVM -D 属性不够。
    # 与固定版本官方 gradle.bat 的真实 JVM/主 JAR 入口一致，不猜测旧版本类名。
    return @('-Xmx64m', '-Xms64m',
        "-javaagent:$($Layout.GradleInstrumentationAgent)",
        "-Dorg.gradle.java.home=$($Layout.JdkHome)", '-Dorg.gradle.appname=gradle',
        '-classpath', '', '-jar', $Layout.GradleCliJar,
        '--no-daemon', '--console=plain',
        '-Porg.gradle.java.installations.auto-download=false',
        '-Porg.gradle.java.installations.auto-detect=false',
        "-Porg.gradle.java.installations.paths=$($Layout.JdkHome)") + $Arguments
}

function New-AndroidProcessStartInfo {
    param(
        [string]$Executable,
        [AllowEmptyCollection()][string[]]$Arguments = @(),
        [hashtable]$Layout
    )
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    if ((Get-Location).Provider.Name -ne 'FileSystem') {
        throw '请从文件系统项目目录运行 Android 开发命令。'
    }
    $startInfo.WorkingDirectory = (Get-Location).ProviderPath
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    # 只修改即将创建的子进程环境，父终端及用户/系统注册表均保持不变。
    $startInfo.Environment['JAVA_HOME'] = $Layout.JdkHome
    $startInfo.Environment['ANDROID_HOME'] = $Layout.SdkRoot
    $startInfo.Environment['ANDROID_SDK_ROOT'] = $Layout.SdkRoot
    $startInfo.Environment['GRADLE_USER_HOME'] = $Layout.GradleUserHome
    return $startInfo
}

function Invoke-AndroidProcess {
    param(
        [string]$Executable,
        [AllowEmptyCollection()][string[]]$Arguments = @(),
        [hashtable]$Layout,
        [ValidateRange(1, 3600)][int]$LimitSeconds
    )
    $process = [Diagnostics.Process]::new()
    try {
        $process.StartInfo = New-AndroidProcessStartInfo $Executable $Arguments $Layout
        $clock = [Diagnostics.Stopwatch]::StartNew()
        $null = $process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $outputTasks = [Threading.Tasks.Task]::WhenAll([Threading.Tasks.Task[]]@($stdout, $stderr))
        $remaining = [Math]::Max(0, ($LimitSeconds * 1000) - [int]$clock.ElapsedMilliseconds)
        $timedOut = -not $process.WaitForExit($remaining)
        if (-not $timedOut) {
            # 父进程退出不代表管道已关闭，进程与输出共同使用同一个截止时间。
            $remaining = [Math]::Max(0, ($LimitSeconds * 1000) - [int]$clock.ElapsedMilliseconds)
            $timedOut = -not $outputTasks.Wait($remaining)
        }
        if ($timedOut) {
            if (-not $process.HasExited) {
                try {
                    # 只终止本函数创建、仍可定位的进程树，不按名称结束其他工具。
                    $process.Kill($true)
                    $null = $process.WaitForExit(2000)
                }
                catch [InvalidOperationException] {
                    # 进程可能刚好在状态检查后退出，不按名称追杀已脱离的后代。
                }
            }
            try { $null = $outputTasks.Wait(1000) } catch [AggregateException] { }
            if ($stdout.IsCompletedSuccessfully) {
                [Console]::Out.Write($stdout.GetAwaiter().GetResult())
            }
            if ($stderr.IsCompletedSuccessfully) {
                [Console]::Error.Write($stderr.GetAwaiter().GetResult())
            }
            # 关闭仍被后代持有的读流；不能无期限 GetResult 等待 EOF。
            $process.StandardOutput.Dispose()
            $process.StandardError.Dispose()
            throw [TimeoutException]::new("Android 开发命令或输出超过 $LimitSeconds 秒；已停止本次仍可定位的进程并关闭读流。")
        }
        [Console]::Out.Write($stdout.GetAwaiter().GetResult())
        [Console]::Error.Write($stderr.GetAwaiter().GetResult())
        return $process.ExitCode
    }
    finally {
        $process.Dispose()
    }
}

# 点源只加载可测试函数，不启动工具，也不写入环境或缓存。
if ($MyInvocation.InvocationName -eq '.') {
    return
}

try {
    foreach ($optionName in @('JDK_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS')) {
        if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($optionName, 'Process'))) {
            throw "当前终端存在 $optionName，会改变 Java 启动参数。请使用没有该覆盖项的终端；本脚本不会替你修改全局设置。"
        }
    }
    $layout = Get-AndroidToolchain $Mode $JdkHome $SdkRoot $GradleHome $GradleUserHome
    if ($Mode -eq 'doctor') {
        if ($ToolArguments.Count -ne 0) {
            throw 'doctor 不接受额外工具参数。'
        }
        Write-Host '检查固定 JDK 21.0.12.1+1、SDK 36、Build Tools 36.0.0、命令行工具 22.0、Gradle 8.14.3。'
        foreach ($check in @(
            @{ Executable = $layout.Java; Arguments = @('-version') },
            @{ Executable = $layout.Javac; Arguments = @('-version') },
            @{ Executable = $layout.Java; Arguments = @(Get-AndroidJavaArguments sdk $layout @('--version')) },
            @{ Executable = $layout.Java; Arguments = @(Get-AndroidJavaArguments gradle $layout @('--version')) }
        )) {
            $result = Invoke-AndroidProcess $check.Executable $check.Arguments $layout ([Math]::Min($TimeoutSeconds, 60))
            if ($result -ne 0) { exit $result }
        }
        Write-Host '环境检查通过；不代表 Android App、APK 或真机验收已经完成。'
        exit 0
    }
    if ($ToolArguments.Count -eq 0) {
        $ToolArguments = if ($Mode -eq 'sdk') { @('--list_installed') } else { @('--version') }
    }
    $javaArguments = @(Get-AndroidJavaArguments $Mode $layout $ToolArguments)
    exit (Invoke-AndroidProcess $layout.Java $javaArguments $layout $TimeoutSeconds)
}
catch [TimeoutException] {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 124
}
catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
