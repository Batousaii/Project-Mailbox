# Upgrade an existing installation only. No historical audit, no activation change.
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'EE-ReliabilityAgent'
$app = Join-Path $root 'app'
$python = Join-Path $root 'venv\Scripts\python.exe'
$pythonw = Join-Path $root 'venv\Scripts\pythonw.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'
$backup = Join-Path $root ('upgrade-backups\' + $stamp)
$staging = Join-Path $root ('upgrade-stage-' + $stamp)
$swapped = $false
$paused = $false
function Run-Python([string[]]$arguments) {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw ('Python check failed, exit ' + $LASTEXITCODE) }
}
function AgentProcesses {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.ExecutablePath -and
        ($_.ExecutablePath -eq $python -or $_.ExecutablePath -eq $pythonw) -and
        $_.CommandLine -match 'agent\.cli\s+daemon' })
}
function Stop-Agent {
    foreach ($p in @(AgentProcesses)) { Stop-Process -Id $p.ProcessId -Force }
    Start-Sleep -Seconds 2
    if (@(AgentProcesses).Count -gt 0) { throw 'Agent could not be stopped safely' }
}
function Start-Agent {
    if (@(AgentProcesses).Count -eq 0) {
        Start-Process -FilePath $pythonw -ArgumentList '-m agent.cli daemon' -WorkingDirectory $app -WindowStyle Hidden | Out-Null
    }
}
try {
    foreach ($p in @($python,$pythonw,(Join-Path $app 'agent\runner.py'),(Join-Path $root 'data\agent.db'))) {
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw ('Existing installation component missing: ' + $p) }
    }
    if (@(AgentProcesses).Count -gt 1) { throw 'Multiple agents found; update blocked' }
    Push-Location $PSScriptRoot
    try { Run-Python -arguments @('-m','unittest','discover','-s','tests_update','-v') }
    finally { Pop-Location }
    New-Item -ItemType Directory -Path $backup | Out-Null
    Copy-Item -LiteralPath $app -Destination $staging -Recurse
    Copy-Item -Path (Join-Path $PSScriptRoot 'app\agent\*.py') -Destination (Join-Path $staging 'agent') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app\agent\role_knowledge.json') -Destination (Join-Path $staging 'agent') -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $staging 'tests') | Out-Null
    Copy-Item -Path (Join-Path $PSScriptRoot 'app\tests\*.py') -Destination (Join-Path $staging 'tests') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app\policy_upgrade_helper.py') -Destination $staging -Force
    Push-Location $staging
    try {
        Run-Python -arguments @('-m','unittest','discover','-s','tests','-v')
        Run-Python -arguments @('-m','agent.cli','preflight')
        Run-Python -arguments @('-m','agent.role_eval','--output',(Join-Path $staging 'role-evaluation.json'))
    } finally { Pop-Location }
    $paused = $true
    Stop-Agent
    Run-Python -arguments @((Join-Path $PSScriptRoot 'update_control.py'),'backup','--root',$root,'--destination',(Join-Path $backup 'agent.db'))
    Move-Item -LiteralPath $app -Destination (Join-Path $backup 'app')
    try { Move-Item -LiteralPath $staging -Destination $app; $swapped = $true }
    catch { Move-Item -LiteralPath (Join-Path $backup 'app') -Destination $app; throw }
    $since = [DateTimeOffset]::UtcNow.ToString('o')
    Start-Agent
    New-Item -ItemType File -Force -Path (Join-Path $root 'data\scan.trigger') | Out-Null
    $ready = $false
    for ($i=0;$i -lt 60;$i++) {
        Start-Sleep -Seconds 5
        if (@(AgentProcesses).Count -eq 0) { throw 'New agent exited' }
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $probeOutput = & $python (Join-Path $PSScriptRoot 'update_control.py') ready --root $root --since $since 2>&1
            $probeExit = $LASTEXITCODE
        } finally { $ErrorActionPreference = $previousPreference }
        foreach ($line in $probeOutput) { Write-Host ([string]$line) }
        if ($probeExit -ne 0 -and $probeExit -ne 2) { throw ('Readiness checker failed, exit ' + $probeExit) }
        if ($probeExit -eq 0 -and @(AgentProcesses).Count -eq 1) { $ready = $true; break }
    }
    Push-Location $app
    try { Run-Python -arguments @('-m','agent.cli','status') } finally { Pop-Location }
    if (-not $ready) {
        Write-Host 'Code updated, but first successful scan NOT verified within 5 minutes. Agent remains active; check STATUS.bat.' -ForegroundColor Yellow
        Write-Host ('Backup: ' + $backup)
        exit 2
    }
    Write-Host 'Update complete: exactly one agent, heartbeat and first successful scan verified. Existing forwarding approval retained.' -ForegroundColor Green
    Write-Host 'Existing login startup configuration retained; an actual logout/login test is still required.'
    Write-Host ('Backup: ' + $backup)
    exit 0
} catch {
    Write-Host ('UPDATE FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    if ($swapped) {
        try {
            Stop-Agent
            Move-Item -LiteralPath $app -Destination (Join-Path $backup 'failed-app')
            Move-Item -LiteralPath (Join-Path $backup 'app') -Destination $app
            Write-Host 'Previous code restored. Database NOT rolled back, to preserve any send outcomes.'
        } catch { Write-Host ('Code rollback failed: ' + $_.Exception.Message); exit 1 }
    }
    if ($paused) {
        try { Start-Agent } catch { Write-Host ('Previous agent restart failed: ' + $_.Exception.Message) }
    }
    Write-Host ('Diagnostic/backup directory: ' + $backup)
    exit 1
}
