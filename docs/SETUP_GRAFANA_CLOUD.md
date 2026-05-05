# Grafana Cloud Setup

Collects Python app logs + Windows metrics + Windows Event Logs via Grafana Alloy.

## Quick Start

### 1. Get Credentials from Grafana Cloud

Go to **Connections** > **Add new connection** > **Windows Server** > **Install integration**

Note these values:
- Loki URL & User ID
- Prometheus URL & User ID
- API Token

### 2. Run Setup Script (PowerShell as Admin)

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

.\Setup-GrafanaAlloy.ps1 `
    -LokiUrl "https://logs-prod-042.grafana.net/loki/api/v1/push" `
    -LokiUserId "1441915" `
    -PrometheusUrl "https://prometheus-prod-66-prod-us-east-3.grafana.net/api/prom/push" `
    -PrometheusUserId "2892477" `
    -ApiToken "glc_eyJ..." `
    -LogPath "C:\path\to\mpi-backend\logs"
```

### 3. Verify

```powershell
Get-Process alloy
```

---

## Query Examples

| Data | Query |
|------|-------|
| App logs | `{app="mpi-backend"}` |
| App errors | `{app="mpi-backend", level="ERROR"}` |
| Windows events | `{job="integrations/windows_exporter"}` |
| CPU usage | `100 - (avg(rate(windows_cpu_time_total{mode="idle"}[5m])) * 100)` |

---

## Common Commands

| Action | Command |
|--------|---------|
| Check running | `Get-Process alloy` |
| Restart | `Stop-Process -Name alloy -Force; Start-ScheduledTask -TaskName "Grafana Alloy"` |
| Debug | `& "C:\Program Files\Grafana Alloy\alloy.exe" run "C:\ProgramData\Grafana Alloy\config.alloy"` |
| Edit config | `notepad "C:\ProgramData\Grafana Alloy\config.alloy"` |
