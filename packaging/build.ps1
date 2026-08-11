$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit code $LASTEXITCODE"
    }
}

function Assert-Signed {
    param([string]$Path)
    $Signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($Signature.Status -ne "Valid") {
        throw "Authenticode verification failed for $Path`: $($Signature.Status)"
    }
}

if ($env:VISION_MCP_OFFICIAL_RELEASE -eq "1" -and -not $env:SIGN_CERT_SHA1) {
    throw "Official release requires SIGN_CERT_SHA1. Leave VISION_MCP_OFFICIAL_RELEASE unset only for an unsigned local test build."
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "需要 Python 3.12 构建环境（最终用户不需要 Python）"
}
$PythonCheck = & py -3.12 -c 'import sys; print(sys.version_info.major,sys.version_info.minor,sys.maxsize>2**32)'
if ($LASTEXITCODE -ne 0 -or $PythonCheck.Trim() -ne "3 12 True") {
    throw "构建必须使用 Python 3.12 x64，当前检测结果: $PythonCheck"
}

$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$ReuseBuildVenv = $env:VISION_MCP_REUSE_BUILD_VENV -eq "1"
$BuildVenvName = if ($ReuseBuildVenv) {
    "vision-mcp-build-venv"
} else {
    "vision-mcp-build-venv-$PID-$([Guid]::NewGuid().ToString('N'))"
}
$BuildVenv = [IO.Path]::GetFullPath((Join-Path $TempRoot $BuildVenvName))
if (-not $BuildVenv.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "构建环境必须位于系统临时目录: $BuildVenv"
}

try {
if ($ReuseBuildVenv) {
    if (-not (Test-Path -LiteralPath (Join-Path $BuildVenv "Scripts\python.exe"))) {
        throw "Requested build-environment reuse, but Python is missing: $BuildVenv"
    }
    Write-Host "Reuse previously validated clean build environment: $BuildVenv"
} else {
    Write-Host "Clean build environment: $BuildVenv"
    Invoke-Checked "py" @("-3.12", "-m", "venv", $BuildVenv)
}
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
$BuildPythonCheck = & $BuildPython -c 'import sys; print(sys.version_info.major,sys.version_info.minor,sys.maxsize>2**32)'
if ($LASTEXITCODE -ne 0 -or $BuildPythonCheck.Trim() -ne "3 12 True") {
    throw "构建虚拟环境必须使用 Python 3.12 x64，当前检测结果: $BuildPythonCheck"
}
$PipArguments = @("-m", "pip", "install", "-r", "requirements.lock")
if ($env:VISION_MCP_OFFICIAL_RELEASE -eq "1") {
    if (-not (Select-String -LiteralPath "requirements.lock" -SimpleMatch "--hash=sha256:" -Quiet)) {
        throw "Official release requires a hash-locked requirements.lock. Regenerate it from reviewed Windows CPython 3.12 x64 wheels."
    }
    $PipArguments += "--require-hashes"
}
if (-not $ReuseBuildVenv) {
    Invoke-Checked $BuildPython $PipArguments
}
Invoke-Checked $BuildPython @("packaging\generate_icon.py")
Invoke-Checked $BuildPython @("-m", "pytest")
Invoke-Checked $BuildPython @(
    "-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", "dist\VisionMCP", "packaging\vision-mcp.spec"
)

$WebView2Bootstrapper = Join-Path $Root "build\MicrosoftEdgeWebview2Setup.exe"
Write-Host "Download Microsoft Edge WebView2 Evergreen Bootstrapper"
Invoke-WebRequest -UseBasicParsing "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $WebView2Bootstrapper
$WebView2Signature = Get-AuthenticodeSignature -LiteralPath $WebView2Bootstrapper
if ($WebView2Signature.Status -ne "Valid" -or $WebView2Signature.SignerCertificate.Subject -notlike "*Microsoft Corporation*") {
    throw "WebView2 Bootstrapper signature validation failed: $($WebView2Signature.Status)"
}

if ($env:SIGN_CERT_SHA1) {
    $SignArgs = @("sign", "/sha1", $env:SIGN_CERT_SHA1, "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256")
    Invoke-Checked "signtool.exe" ($SignArgs + "dist\VisionMCP\vision-mcp-server.exe")
    Invoke-Checked "signtool.exe" ($SignArgs + "dist\VisionMCP\Vision MCP 管理器.exe")
    Assert-Signed "dist\VisionMCP\vision-mcp-server.exe"
    Assert-Signed "dist\VisionMCP\Vision MCP 管理器.exe"
}

$Iscc = if ($env:ISCC_PATH) {
    $env:ISCC_PATH
} else {
    @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not (Test-Path $Iscc)) { throw "未找到 Inno Setup 6；请设置 ISCC_PATH" }
Invoke-Checked $Iscc @("packaging\installer.iss")

if ($env:SIGN_CERT_SHA1) {
    Get-ChildItem dist-installer\*.exe | ForEach-Object {
        Invoke-Checked "signtool.exe" ($SignArgs + $_.FullName)
        Assert-Signed $_.FullName
    }
}

Get-ChildItem dist-installer\*.exe | ForEach-Object {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
    Set-Content -LiteralPath ($_.FullName + ".sha256") -Value "$Hash  $($_.Name)" -Encoding ascii
}
} finally {
    if (-not $ReuseBuildVenv -and (Test-Path -LiteralPath $BuildVenv)) {
        $ResolvedVenv = (Resolve-Path -LiteralPath $BuildVenv).Path
        $ResolvedLeaf = Split-Path -Leaf $ResolvedVenv
        if ($ResolvedVenv.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase) -and
            $ResolvedLeaf.StartsWith("vision-mcp-build-venv-", [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
        } else {
            Write-Warning "跳过清理意外的构建环境路径: $ResolvedVenv"
        }
    }
}
