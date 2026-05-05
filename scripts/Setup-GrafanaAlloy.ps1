#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installs and configures Grafana Alloy for MPI Backend log shipping + Windows metrics to Grafana Cloud.

.DESCRIPTION
    This script:
    1. Downloads Grafana Alloy for Windows
    2. Creates configuration file with:
       - Python app log collection (your backend logs)
       - Windows performance metrics (CPU, disk, network, etc.)
       - Windows Event Logs (Application, System)
    3. Installs as Windows Scheduled Task (runs at startup as SYSTEM)
    4. Starts Alloy immediately
    5. Validates the setup

.PARAMETER LokiUrl
    Grafana Cloud Loki push URL (e.g., https://logs-prod-042.grafana.net/loki/api/v1/push)

.PARAMETER LokiUserId
    Your Grafana Cloud Loki numeric user ID

.PARAMETER PrometheusUrl
    Grafana Cloud Prometheus push URL (e.g., https://prometheus-prod-66-prod-us-east-3.grafana.net/api/prom/push)

.PARAMETER PrometheusUserId
    Your Grafana Cloud Prometheus numeric user ID

.PARAMETER ApiToken
    Your Grafana Cloud API token with logs:write and metrics:write scopes

.PARAMETER LogPath
    Path to the mpi-backend logs directory

.PARAMETER ScrapeInterval
    Metrics scrape interval (default: 60s)

.EXAMPLE
    .\Setup-GrafanaAlloy.ps1 `
        -LokiUrl "https://logs-prod-042.grafana.net/loki/api/v1/push" `
        -LokiUserId "1441915" `
        -PrometheusUrl "https://prometheus-prod-66-prod-us-east-3.grafana.net/api/prom/push" `
        -PrometheusUserId "2892477" `
        -ApiToken "glc_xxx" `
        -LogPath "C:\apps\mpi-backend\logs"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$LokiUrl,

    [Parameter(Mandatory=$true)]
    [string]$LokiUserId,

    [Parameter(Mandatory=$true)]
    [string]$PrometheusUrl,

    [Parameter(Mandatory=$true)]
    [string]$PrometheusUserId,

    [Parameter(Mandatory=$true)]
    [string]$ApiToken,

    [Parameter(Mandatory=$true)]
    [string]$LogPath,

    [Parameter(Mandatory=$false)]
    [string]$ScrapeInterval = "60s"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Speed up downloads

# Configuration
$AlloyVersion = "v1.4.2"
$InstallDir = "C:\Program Files\Grafana Alloy"
$ConfigDir = "C:\ProgramData\Grafana Alloy"
$ServiceName = "Alloy"

# Colors for output
function Write-Step { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Failure { param($msg) Write-Host "[FAIL] $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "    $msg" -ForegroundColor Gray }

$errors = @()

Write-Host @"
============================================
Grafana Alloy Setup for Windows
============================================
Version: $AlloyVersion
Install Dir: $InstallDir
Config Dir: $ConfigDir
Log Path: $LogPath
Loki URL: $LokiUrl
Prometheus URL: $PrometheusUrl
Scrape Interval: $ScrapeInterval
============================================
"@ -ForegroundColor Yellow

# Step 1: Validate log path
Write-Step "Validating log path..."
if (Test-Path $LogPath) {
    $logFiles = Get-ChildItem -Path $LogPath -Filter "*.log" -ErrorAction SilentlyContinue
    if ($logFiles.Count -gt 0) {
        Write-Success "Found $($logFiles.Count) log file(s) in $LogPath"
        $logFiles | ForEach-Object { Write-Info $_.Name }
    } else {
        Write-Failure "No .log files found in $LogPath"
        $errors += "No log files found at specified path"
    }
} else {
    Write-Failure "Log path does not exist: $LogPath"
    $errors += "Log path does not exist"
}

# Step 2: Download Alloy
Write-Step "Downloading Grafana Alloy $AlloyVersion..."
$downloadUrl = "https://github.com/grafana/alloy/releases/download/$AlloyVersion/alloy-windows-amd64.exe.zip"
$zipPath = "$env:TEMP\alloy-windows-amd64.zip"

try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
    Write-Success "Downloaded Alloy to $zipPath"
} catch {
    Write-Failure "Failed to download Alloy: $_"
    $errors += "Download failed: $_"
}

# Step 3: Extract and install
Write-Step "Installing Alloy..."
try {
    # Create directories
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null

    # Extract
    Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force

    # Rename if needed (zip contains alloy-windows-amd64.exe)
    $exePath = Join-Path $InstallDir "alloy-windows-amd64.exe"
    $targetExe = Join-Path $InstallDir "alloy.exe"
    if (Test-Path $exePath) {
        Move-Item -Path $exePath -Destination $targetExe -Force
    }

    if (Test-Path $targetExe) {
        Write-Success "Installed Alloy to $targetExe"
    } else {
        Write-Failure "Alloy executable not found after extraction"
        $errors += "Installation failed - exe not found"
    }
} catch {
    Write-Failure "Installation failed: $_"
    $errors += "Installation error: $_"
}

# Step 4: Create configuration
Write-Step "Creating configuration file..."
$configPath = Join-Path $ConfigDir "config.alloy"

# Escape backslashes for the config file
$escapedLogPath = $LogPath -replace '\\', '/'

$configContent = @"
// ============================================
// Grafana Alloy Configuration
// MPI Backend + Windows Metrics + Windows Event Logs
// Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
// ============================================

// ============================================
// PROMETHEUS METRICS - Remote Write Endpoint
// ============================================

prometheus.remote_write "metrics_service" {
  endpoint {
    url = "$PrometheusUrl"

    basic_auth {
      username = "$PrometheusUserId"
      password = "$ApiToken"
    }
  }
}

// ============================================
// LOKI LOGS - Remote Write Endpoint
// ============================================

loki.write "grafana_cloud_loki" {
  endpoint {
    url = "$LokiUrl"

    basic_auth {
      username = "$LokiUserId"
      password = "$ApiToken"
    }
  }
}

// ============================================
// WINDOWS PERFORMANCE METRICS
// ============================================

prometheus.exporter.windows "integrations_windows_exporter" {
  enabled_collectors = ["cpu", "cs", "logical_disk", "net", "os", "service", "system", "time", "diskdrive"]
}

discovery.relabel "integrations_windows_exporter" {
  targets = prometheus.exporter.windows.integrations_windows_exporter.targets

  rule {
    target_label = "job"
    replacement  = "integrations/windows_exporter"
  }

  rule {
    target_label = "instance"
    replacement  = constants.hostname
  }
}

prometheus.scrape "integrations_windows_exporter" {
  targets    = discovery.relabel.integrations_windows_exporter.output
  forward_to = [prometheus.relabel.integrations_windows_exporter.receiver]
  job_name   = "integrations/windows_exporter"
  scrape_interval = "$ScrapeInterval"
}

prometheus.relabel "integrations_windows_exporter" {
  forward_to = [prometheus.remote_write.metrics_service.receiver]

  rule {
    source_labels = ["volume"]
    regex         = "HarddiskVolume.*"
    action        = "drop"
  }

  rule {
    action = "keep"
    regex = "up|windows_cpu_interrupts_total|windows_cpu_time_total|windows_cs_hostname|windows_cs_logical_processors|windows_cs_physical_memory_bytes|windows_disk_drive_status|windows_logical_disk_avg_read_requests_queued|windows_logical_disk_avg_write_requests_queued|windows_logical_disk_free_bytes|windows_logical_disk_idle_seconds_total|windows_logical_disk_read_bytes_total|windows_logical_disk_read_seconds_total|windows_logical_disk_reads_total|windows_logical_disk_size_bytes|windows_logical_disk_write_bytes_total|windows_logical_disk_write_seconds_total|windows_logical_disk_writes_total|windows_net_bytes_received_total|windows_net_bytes_sent_total|windows_net_packets_outbound_discarded_total|windows_net_packets_outbound_errors_total|windows_net_packets_received_discarded_total|windows_net_packets_received_errors_total|windows_net_packets_received_unknown_total|windows_os_info|windows_os_paging_limit_bytes|windows_os_physical_memory_free_bytes|windows_os_timezone|windows_service_status|windows_system_context_switches_total|windows_system_processor_queue_length|windows_system_system_up_time|windows_time_computed_time_offset_seconds|windows_time_ntp_round_trip_delay_seconds|"
    source_labels = ["__name__"]
  }
}

// ============================================
// WINDOWS EVENT LOGS - Application
// ============================================

loki.source.windowsevent "logs_integrations_windows_exporter_application" {
  locale                 = 1033
  eventlog_name          = "Application"
  bookmark_path          = "./bookmarks-app.xml"
  poll_interval          = "0s"
  use_incoming_timestamp = true
  forward_to             = [loki.relabel.logs_integrations_windows_exporter_application.receiver]
  labels                 = {
    instance = constants.hostname,
    job      = "integrations/windows_exporter",
  }
}

loki.relabel "logs_integrations_windows_exporter_application" {
  forward_to = [loki.process.logs_integrations_windows_exporter_application.receiver]

  rule {
    source_labels = ["computer"]
    target_label  = "agent_hostname"
  }
}

loki.process "logs_integrations_windows_exporter_application" {
  forward_to = [loki.write.grafana_cloud_loki.receiver]

  stage.json {
    expressions = {
      level  = "levelText",
      source = "source",
    }
  }

  stage.labels {
    values = {
      level  = "",
      source = "",
    }
  }
}

// ============================================
// WINDOWS EVENT LOGS - System
// ============================================

loki.source.windowsevent "logs_integrations_windows_exporter_system" {
  locale                 = 1033
  eventlog_name          = "System"
  bookmark_path          = "./bookmarks-sys.xml"
  poll_interval          = "0s"
  use_incoming_timestamp = true
  forward_to             = [loki.relabel.logs_integrations_windows_exporter_system.receiver]
  labels                 = {
    instance = constants.hostname,
    job      = "integrations/windows_exporter",
  }
}

loki.relabel "logs_integrations_windows_exporter_system" {
  forward_to = [loki.process.logs_integrations_windows_exporter_system.receiver]

  rule {
    source_labels = ["computer"]
    target_label  = "agent_hostname"
  }
}

loki.process "logs_integrations_windows_exporter_system" {
  forward_to = [loki.write.grafana_cloud_loki.receiver]

  stage.json {
    expressions = {
      level  = "levelText",
      source = "source",
    }
  }

  stage.labels {
    values = {
      level  = "",
      source = "",
    }
  }
}

// ============================================
// MPI BACKEND PYTHON APP LOGS
// ============================================

local.file_match "backend_logs" {
  path_targets = [
    {
      __path__ = "$escapedLogPath/*.log",
      app      = "mpi-backend",
      env      = "production",
    },
  ]
}

loki.source.file "backend" {
  targets    = local.file_match.backend_logs.targets
  forward_to = [loki.process.parse_backend_logs.receiver]
}

loki.process "parse_backend_logs" {
  forward_to = [loki.write.grafana_cloud_loki.receiver]

  // Extract structured data from log lines
  // Format: [timestamp - module->function():line]LEVEL: message
  stage.regex {
    expression = "^\\[(?P<timestamp>\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}) - (?P<module>[^->]+)->(?P<function>[^(]+)\\(\\):(?P<line>\\d+)\\](?P<level>\\w+): (?P<message>.*)$"
  }

  // Add extracted fields as labels for filtering in Grafana
  stage.labels {
    values = {
      level  = "",
      module = "",
    }
  }

  // Add static labels
  stage.static_labels {
    values = {
      service = "invoice-processor",
    }
  }
}

// ============================================
// MPI BACKEND SCRIPT LOGS (separate from main app)
// ============================================

local.file_match "script_logs" {
  path_targets = [
    {
      __path__ = "$escapedLogPath/scripts/*.log",
      job      = "mpi-scripts",
      env      = "production",
    },
  ]
}

loki.source.file "scripts" {
  targets    = local.file_match.script_logs.targets
  forward_to = [loki.process.parse_script_logs.receiver]
}

loki.process "parse_script_logs" {
  forward_to = [loki.write.grafana_cloud_loki.receiver]

  // Same regex as main app - format: [timestamp - module->function():line]LEVEL: message
  stage.regex {
    expression = "^\\[(?P<timestamp>\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}) - (?P<module>[^->]+)->(?P<function>[^(]+)\\(\\):(?P<line>\\d+)\\](?P<level>\\w+): (?P<message>.*)$"
  }

  stage.labels {
    values = {
      level  = "",
      module = "",
    }
  }

  stage.static_labels {
    values = {
      service = "invoice-processor",
    }
  }
}
"@

try {
    $configContent | Out-File -FilePath $configPath -Encoding UTF8 -Force
    Write-Success "Created configuration at $configPath"
} catch {
    Write-Failure "Failed to create config: $_"
    $errors += "Config creation failed: $_"
}

# Step 5: Validate configuration
Write-Step "Validating configuration..."
$alloyExe = Join-Path $InstallDir "alloy.exe"
if (Test-Path $alloyExe) {
    try {
        $validateResult = & $alloyExe fmt $configPath 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Configuration syntax is valid"
        } else {
            Write-Failure "Configuration validation failed: $validateResult"
            $errors += "Config validation error"
        }
    } catch {
        Write-Info "Could not validate config (non-critical): $_"
    }
}

# Step 6: Remove existing scheduled task if present
Write-Step "Checking for existing scheduled task..."
$existingTask = Get-ScheduledTask -TaskName "Grafana Alloy" -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Info "Stopping existing task..."
    Stop-ScheduledTask -TaskName "Grafana Alloy" -ErrorAction SilentlyContinue

    # Kill any running alloy process
    Get-Process -Name "alloy" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    Write-Info "Removing existing scheduled task..."
    Unregister-ScheduledTask -TaskName "Grafana Alloy" -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Write-Success "Removed existing scheduled task"
}

# Also clean up any old Windows service
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Info "Removing old Windows service..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    & sc.exe delete $ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}

# Step 7: Install as Scheduled Task (more reliable than Windows Service for Alloy)
Write-Step "Installing as scheduled task..."

try {
    # Create the scheduled task action
    $action = New-ScheduledTaskAction -Execute $alloyExe -Argument "run `"$configPath`""

    # Run at startup, with highest privileges, as SYSTEM
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    # Settings: restart on failure, don't stop on idle, run indefinitely
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 9999)

    # Register the task
    Register-ScheduledTask -TaskName "Grafana Alloy" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Grafana Alloy - Log and metrics collector for Grafana Cloud" | Out-Null

    Write-Success "Scheduled task created: Grafana Alloy"
} catch {
    Write-Failure "Failed to create scheduled task: $_"
    $errors += "Scheduled task creation failed: $_"
}

# Step 8: Start the task immediately
Write-Step "Starting Grafana Alloy..."
try {
    Start-ScheduledTask -TaskName "Grafana Alloy"
    Start-Sleep -Seconds 3

    # Verify process is running
    $process = Get-Process -Name "alloy" -ErrorAction SilentlyContinue
    if ($process) {
        Write-Success "Alloy is running (PID: $($process.Id))"
    } else {
        Write-Failure "Alloy process not found"
        $errors += "Alloy failed to start"
    }
} catch {
    Write-Failure "Failed to start Alloy: $_"
    $errors += "Alloy start failed: $_"
}

# Step 9: Verify connectivity
Write-Step "Testing Grafana Cloud connectivity..."
try {
    # Test Loki
    $lokiUri = [System.Uri]$LokiUrl
    $lokiHost = $lokiUri.Host
    $lokiResult = Test-NetConnection -ComputerName $lokiHost -Port 443 -WarningAction SilentlyContinue
    if ($lokiResult.TcpTestSucceeded) {
        Write-Success "Can reach Loki ($lokiHost:443)"
    } else {
        Write-Failure "Cannot reach Loki - check firewall"
        $errors += "Network connectivity to Loki failed"
    }

    # Test Prometheus
    $promUri = [System.Uri]$PrometheusUrl
    $promHost = $promUri.Host
    $promResult = Test-NetConnection -ComputerName $promHost -Port 443 -WarningAction SilentlyContinue
    if ($promResult.TcpTestSucceeded) {
        Write-Success "Can reach Prometheus ($promHost:443)"
    } else {
        Write-Failure "Cannot reach Prometheus - check firewall"
        $errors += "Network connectivity to Prometheus failed"
    }
} catch {
    Write-Info "Connectivity test skipped: $_"
}

# Step 10: Final verification
Write-Step "Final verification..."
try {
    $process = Get-Process -Name "alloy" -ErrorAction SilentlyContinue
    $task = Get-ScheduledTask -TaskName "Grafana Alloy" -ErrorAction SilentlyContinue

    if ($process -and $task) {
        Write-Success "Alloy is running and scheduled task is configured"
    } elseif ($task -and -not $process) {
        Write-Failure "Scheduled task exists but Alloy is not running"
        $errors += "Alloy not running"
    } else {
        Write-Failure "Setup incomplete"
        $errors += "Setup verification failed"
    }
} catch {
    Write-Info "Could not verify status: $_"
}

# Summary
Write-Host "`n============================================" -ForegroundColor Yellow
Write-Host "SETUP SUMMARY" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow

if ($errors.Count -eq 0) {
    Write-Host "`n[SUCCESS] Grafana Alloy installed and running!" -ForegroundColor Green
    Write-Host @"

What's being collected:
  - Python app logs:     {app="mpi-backend"}
  - Python script logs:  {job="mpi-scripts"}
  - Windows Event Logs:  {job="integrations/windows_exporter"}
  - Windows Metrics:     Use Prometheus data source in Grafana

Next steps:
1. Wait 1-2 minutes for data to appear in Grafana Cloud
2. Go to your Grafana Cloud instance
3. For logs: Explore > Loki data source
4. For metrics: Explore > Prometheus data source (or use pre-built Windows dashboard)

Useful commands:
  - Check if running:      Get-Process alloy
  - View task status:      Get-ScheduledTask -TaskName "Grafana Alloy"
  - Restart Alloy:         Stop-Process -Name alloy -Force; Start-ScheduledTask -TaskName "Grafana Alloy"
  - Stop Alloy:            Stop-Process -Name alloy -Force

Config file: $configPath
"@ -ForegroundColor Cyan
} else {
    Write-Host "`n[ERRORS DETECTED]" -ForegroundColor Red
    Write-Host "The following issues were encountered:" -ForegroundColor Red
    $errors | ForEach-Object {
        Write-Host "  - $_" -ForegroundColor Red
    }
    Write-Host "`nPlease resolve these issues and re-run the script." -ForegroundColor Yellow
}

# Cleanup
Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue

Write-Host "`nSetup complete. Errors: $($errors.Count)" -ForegroundColor $(if ($errors.Count -eq 0) { "Green" } else { "Red" })
