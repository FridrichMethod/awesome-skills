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
& $exe @prefix -I -c 'import sys; sys.exit(sys.version_info < (3, 11))'
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Python 3.11+ is required; $($python -join ' ') is older (set SKILLS_PYTHON)"
}

# Python never imports from a folder it was not given: a checkout's installer runs with -P (its own
# folder stays off sys.path; PyYAML may live in the user's site-packages), a download with -I.
# The installer beside this script runs only from a checkout (skills or .git), and off Windows only
# from one this user owns and no one else may write to, scripts and the file included (group write
# only for the user's own private group): a copy of this script staged in a shared temporary folder
# such as /tmp must never run what another user put beside it. Windows' temporary folder is per user.
$owned = @'
import grp, os, pwd, sys
d = sys.argv[1]
ok = True
for p in (d, os.path.join(d, 'scripts'), os.path.join(d, 'scripts', 'install_skills.py')):
    s = os.stat(p)
    try:
        me, g = pwd.getpwuid(os.geteuid()).pw_name, grp.getgrgid(s.st_gid)
        private = g.gr_name == me and set(g.gr_mem) <= {me}
    except KeyError:
        private = False
    ok = ok and s.st_uid == os.geteuid() and not s.st_mode & 0o002 and (private or not s.st_mode & 0o020)
sys.exit(not ok)
'@
$local = if ($PSScriptRoot) { Join-Path (Join-Path $PSScriptRoot 'scripts') 'install_skills.py' } else { '' }
if ($local -and (Test-Path -LiteralPath $local -PathType Leaf)) {
    $checkout = (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'skills') -PathType Container) -or
        (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.git'))
    if ($checkout -and $env:OS -ne 'Windows_NT') {
        & $exe @prefix -I -c $owned $PSScriptRoot
        $checkout = $LASTEXITCODE -eq 0
    }
    if ($checkout) {
        & $exe @prefix -P -B $local @args
        exit $LASTEXITCODE
    }
    [Console]::Error.WriteLine("awesome-skills: not using ${local}: not in a checkout only you can write to; downloading the installer")
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
    & $exe @prefix -I -B $temp --remote @args
    $code = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
exit $code
