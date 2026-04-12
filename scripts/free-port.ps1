param([int]$Port = 8020)
$killed = $false
try {
  Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $p = $_.OwningProcess
    if ($p) {
      Write-Host "Stopping PID $p (port $Port)"
      Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
      $killed = $true
    }
  }
} catch {
}
if (-not $killed) {
  Write-Host "No listener on port $Port."
}
