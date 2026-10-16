param([ValidateSet('Start','Stop','Uninstall')][string]$Action)
$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'EE-ReliabilityAgent'
$app=Join-Path $root 'app'
$python=Join-Path $root 'venv\Scripts\python.exe'
$pythonw=Join-Path $root 'venv\Scripts\pythonw.exe'
function Processes {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
        ($_.ExecutablePath -eq $python -or $_.ExecutablePath -eq $pythonw) -and $_.CommandLine -match 'agent\.cli\s+daemon'
    })
}
try {
    if ($Action -eq 'Start') {
        Remove-Item (Join-Path $root 'data\stop.request') -ErrorAction SilentlyContinue
        if (@(Processes).Count -eq 0) { Start-Process $pythonw -ArgumentList '-m agent.cli daemon' -WorkingDirectory $app -WindowStyle Hidden }
        Write-Host 'Start aangevraagd. Controleer heartbeat en last_scan_success via STATUS.bat.'
    } else {
        New-Item (Join-Path $root 'data\stop.request') -ItemType File -Force | Out-Null
        for ($i=0;$i -lt 40 -and @(Processes).Count -gt 0;$i++) { Start-Sleep -Seconds 2 }
        if (@(Processes).Count -gt 0) { throw 'Agent nog bezig; wacht en probeer opnieuw. Geen proces geforceerd gestopt.' }
        if ($Action -eq 'Uninstall') {
            $shortcut=Join-Path ([Environment]::GetFolderPath('Startup')) 'EE-ReliabilityAgent.lnk'
            if (Test-Path $shortcut) {
                $shell=New-Object -ComObject WScript.Shell
                $link=$shell.CreateShortcut($shortcut)
                if ($link.TargetPath -eq $pythonw) { Remove-Item $shortcut }
            }
            Push-Location $app
            try { & $python -m agent.cli backup; if ($LASTEXITCODE -ne 0) { throw 'Backup mislukt' } } finally { Pop-Location }
            Write-Host 'V2-worker en door INSTALL aangemaakte Startup-snelkoppeling uitgeschakeld. Data/app/venv behouden. Bestaande legacy-taken moeten afzonderlijk worden gecontroleerd.'
        }
    }
} catch { Write-Host $_.Exception.Message -ForegroundColor Red;exit 1 }
