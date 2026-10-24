# Native Windows bootstrap (PowerShell 7; Windows PowerShell 5.1 also works).
# The same command is the first install and every update. Flags are the installer's own and
# pass through unchanged, for example: --codex-only --enable SOURCE_ID, --dry-run, --list.
# Selection, ownership, git transport and locking live in the Python installer.
#
#   $f = Join-Path ([IO.Path]::GetTempPath()) "awesome-skills-$PID.ps1"
#   Invoke-WebRequest -UseBasicParsing -Uri https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.ps1 -OutFile $f
#   pwsh -NoProfile -ExecutionPolicy Bypass -File $f; Remove-Item -LiteralPath $f
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Stop-Install([string]$Message) {
    [Console]::Error.WriteLine("awesome-skills: $Message")
    exit 1
}

$python = @()
if ($env:SKILLS_PYTHON) {
    $python = @($env:SKILLS_PYTHON)
} elseif (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
    $python = @('py', '-3')
} elseif (Get-Command python -CommandType Application -ErrorAction SilentlyContinue) {
    $python = @('python')
} else {
    Stop-Install 'Python 3.11+ is required; none found on PATH (set SKILLS_PYTHON)'
}
$exe = $python[0]
$prefix = @($python | Select-Object -Skip 1)

$local = if ($PSScriptRoot) { Join-Path (Join-Path $PSScriptRoot 'scripts') 'install_skills.py' } else { '' }
if ($local -and (Test-Path -LiteralPath $local -PathType Leaf)) {
    & $exe @prefix -B $local @args
    exit $LASTEXITCODE
}

$branch = if ($env:SKILLS_BRANCH) { $env:SKILLS_BRANCH } else { 'main' }
$url = if ($env:SKILLS_INSTALLER_URL) { $env:SKILLS_INSTALLER_URL } else {
    "https://raw.githubusercontent.com/FridrichMethod/awesome-skills/$branch/scripts/install_skills.py"
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ('awesome-skills-' + [Guid]::NewGuid().ToString('N') + '.py')
$code = 1
try {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $temp
    } catch {
        Stop-Install "could not download the installer from $url"
    }
    & $exe @prefix -B $temp --remote @args
    $code = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
exit $code
