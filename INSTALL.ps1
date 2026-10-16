$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'EE-ReliabilityAgent'
$python=Join-Path $root 'venv\Scripts\python.exe'
$pythonw=Join-Path $root 'venv\Scripts\pythonw.exe'
$app=Join-Path $root 'app'
function Run([string[]]$Arguments) { & $python @Arguments; if ($LASTEXITCODE -ne 0) { throw "Installatiestap mislukt (exit $LASTEXITCODE). Geen gereedmelding." } }
try {
    if (Test-Path (Join-Path $root 'data\agent.db')) {
        & (Join-Path $PSScriptRoot 'UPDATE.ps1')
        exit $LASTEXITCODE
    }
    New-Item $root -ItemType Directory -Force | Out-Null
    $candidates=@()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { $paths=& py -0p 2>$null
            foreach ($line in $paths) { if ($line -match '([A-Za-z]:\\.*python\.exe)\s*$') { $candidates += $Matches[1] } }
        } catch { }
    }
    foreach ($cmd in @('python','python3')) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { $candidates += (Get-Command $cmd).Source }
    }
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName
    $chosen=$null
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        try {
            & $candidate -c 'import sys,venv,struct; sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize(''P'')==8 else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $chosen=$candidate; break }
        } catch { }
    }
    if (!$chosen) { throw 'Installeer 64-bit Python >=3.10 voor huidige gebruiker via python.org. Voer INSTALL.bat opnieuw uit. Geen baseline of startup gemaakt.' }
    & $chosen -m venv (Join-Path $root 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Eigen Python-venv kon niet worden gemaakt/hersteld.' }
    Run -Arguments @('-m','ensurepip','--upgrade')
    Run -Arguments @('-m','pip','install','--disable-pip-version-check','-r',(Join-Path $PSScriptRoot 'requirements.txt'))
    Push-Location (Join-Path $PSScriptRoot 'app')
    try {
        Run -Arguments @('-m','unittest','discover','-s','tests','-v')
        Run -Arguments @('-m','agent.setup')
        Run -Arguments @('-m','agent.cli','preflight')
        Run -Arguments @('-m','agent.role_eval','--output',(Join-Path $PSScriptRoot 'role-evaluation.json'))
        Run -Arguments @('-m','agent.cli','legacy_backup')
    } finally { Pop-Location }
    # All prerequisites and synthetic real-model outcomes passed. Now install app/baseline.
    Copy-Item (Join-Path $PSScriptRoot 'app') $root -Recurse -Force
    Copy-Item (Join-Path $PSScriptRoot 'role-evaluation.json') $app -Force
    Push-Location $app
    try { Run -Arguments @('-m','agent.cli','inventory'); Run -Arguments @('-m','agent.cli','baseline') } finally { Pop-Location }
    $shell=New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'EE-ReliabilityAgent.lnk'))
    $link.TargetPath=$pythonw
    $link.Arguments='-m agent.cli daemon'
    $link.WorkingDirectory=$app
    $link.WindowStyle=7
    $link.Save()
    Remove-Item (Join-Path $root 'data\stop.request') -ErrorAction SilentlyContinue
    $since=[DateTimeOffset]::UtcNow.ToString('o')
    Start-Process $pythonw -ArgumentList '-m agent.cli daemon' -WorkingDirectory $app -WindowStyle Hidden
    $ready=$false
    for ($i=0;$i -lt 60;$i++) {
        Start-Sleep -Seconds 5
        & $python (Join-Path $PSScriptRoot 'update_control.py') ready --root $root --since $since
        if ($LASTEXITCODE -eq 0) { $ready=$true;break }
        if ($LASTEXITCODE -ne 2) { throw 'Readinesscontrole mislukt.' }
    }
    if (!$ready) { Write-Host 'NIET GEREED: eerste scan nog niet bevestigd. Controleer STATUS.bat.';exit 2 }
    Write-Host 'Achtergrondagent en eerste scan bevestigd. Stop eventuele oude ReliabilityAgentClean-opstart. Gebruik ACTIVATE.bat voor goedgekeurde test-forward/activatie.'
} catch { Write-Host ('NIET GEREED: '+$_.Exception.Message) -ForegroundColor Red;exit 1 }
