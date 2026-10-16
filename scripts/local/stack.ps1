param(
    [ValidateSet('up', 'stop', 'status', 'logs', 'check-provider')]
    [string]$Action = 'status',
    [string]$Distribution = 'Ubuntu-24.04'
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$resolvedLinuxPath = & wsl -d $Distribution --exec wslpath -a $projectRoot.Replace('\', '/')
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the project path inside WSL.' }
$linuxRoot = ($resolvedLinuxPath -join "`n").Trim()
$stateDirectory = Join-Path $projectRoot '.cache'
$stateFile = Join-Path $stateDirectory 'wsl-preview-process.json'
$keeper = $null
if (Test-Path -LiteralPath $stateFile) {
    $saved = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $process = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'wsl' -and
        $process.StartTime.ToUniversalTime().Ticks -eq $saved.startTicks) {
        $keeper = $process
    }
}
if ($Action -eq 'up') {
    # systemd services alone do not keep a WSL distribution alive.
    if (-not $keeper) {
        New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
        $keeper = Start-Process wsl.exe -WindowStyle Hidden -PassThru -ArgumentList @(
            '-d', $Distribution, '--exec', 'sleep', 'infinity'
        )
        @{ id = $keeper.Id; startTicks = $keeper.StartTime.ToUniversalTime().Ticks } |
            ConvertTo-Json | Set-Content -LiteralPath $stateFile
    }
    & wsl -d $Distribution -u root -- systemctl start docker
    if ($LASTEXITCODE -ne 0) { throw 'Cannot start Docker in WSL.' }
}
$composeArgs = @('compose', '-f', 'docker-compose.yml', '-f', 'compose.local.yaml')
switch ($Action) {
    'up' { $composeArgs += @('up', '-d', '--build') }
    'stop' { $composeArgs += @('stop') }
    'status' { $composeArgs += @('ps') }
    'logs' { $composeArgs += @('logs', '--tail', '80') }
    'check-provider' {
        # Explicit real-provider probe; no entrypoint migrations or startup seed.
        # Reads API_FOOTBALL_KEY from the git-ignored .env through Compose.
        $composeArgs += @(
            'run', '--rm', '--no-deps', '--entrypoint', 'python',
            '-e', 'DATA_PROVIDER=api_football', 'api',
            '-m', 'edge_ingestion.cli', 'check-provider'
        )
    }
}
& wsl -d $Distribution -u root --cd $linuxRoot -- docker @composeArgs
if ($LASTEXITCODE -ne 0) { throw "Docker compose $Action failed." }
if ($Action -eq 'stop' -and $keeper) {
    Stop-Process -Id $keeper.Id
    Remove-Item -LiteralPath $stateFile
}
