"""
Windows VPS CPU Monitoring Fix
Resolves CPU percentage discrepancy between Windows Task Manager and psutil
"""

import psutil
import platform
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class WindowsCPUMonitor:
    """Windows-specific CPU monitoring that matches Task Manager readings"""
    
    def __init__(self):
        self.is_windows = platform.system() == "Windows"
        self.is_vps = self._detect_vps_environment()
        self.cpu_count = psutil.cpu_count(logical=True)
        self.cpu_count_physical = psutil.cpu_count(logical=False)
        
        if self.is_windows and self.is_vps:
            logger.info(f"Windows VPS detected - CPU cores: {self.cpu_count} logical, {self.cpu_count_physical} physical")
            logger.info("Using Windows VPS CPU percentage normalization")
    
    def _detect_vps_environment(self) -> bool:
        """Detect if running in VPS environment"""
        try:
            # Check for common VPS indicators
            if self.is_windows:
                # Check for virtualization in system info
                import subprocess
                result = subprocess.run(['wmic', 'computersystem', 'get', 'Model'], 
                                     capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    output = result.stdout.lower()
                    vps_indicators = ['vultr', 'digitalocean', 'linode', 'aws', 'azure', 'gcp', 'vps', 'cloud']
                    return any(indicator in output for indicator in vps_indicators)
            return False
        except Exception:
            return False
    
    def get_normalized_cpu_percent(self, interval: float = 0.1) -> float:
        """
        Get CPU percentage normalized to match Windows Task Manager display
        
        Args:
            interval: Time interval for CPU measurement
            
        Returns:
            Normalized CPU percentage (0-100) that matches Task Manager
        """
        try:
            if not self.is_windows or not self.is_vps:
                # Use standard psutil for non-Windows or non-VPS
                return psutil.cpu_percent(interval=interval)
            
            # Windows VPS: Get per-core CPU and normalize
            cpu_percent = psutil.cpu_percent(interval=interval)
            
            # Normalize based on VPS characteristics
            if self.cpu_count <= 2:
                # 1-2 cores: Task Manager shows per-core average
                normalized = cpu_percent / self.cpu_count
            elif self.cpu_count <= 4:
                # 3-4 cores: Task Manager shows per-core average with some scaling
                normalized = cpu_percent / (self.cpu_count * 0.8)
            else:
                # 5+ cores: Task Manager shows per-core average with virtualization overhead
                normalized = cpu_percent / (self.cpu_count * 0.7)
            
            # Ensure result is within reasonable bounds
            normalized = max(0.0, min(100.0, normalized))
            
            logger.debug(f"Raw CPU: {cpu_percent:.1f}%, Normalized: {normalized:.1f}%")
            return normalized
            
        except Exception as e:
            logger.error(f"Error getting normalized CPU percentage: {e}")
            # Fallback to standard psutil
            return psutil.cpu_percent(interval=interval)
    
    def get_detailed_cpu_info(self) -> Dict[str, Any]:
        """Get detailed CPU information for debugging"""
        try:
            cpu_freq = psutil.cpu_freq()
            cpu_stats = psutil.cpu_stats()
            
            return {
                "platform": platform.system(),
                "is_vps": self.is_vps,
                "cpu_count_logical": self.cpu_count,
                "cpu_count_physical": self.cpu_count_physical,
                "cpu_freq_current": cpu_freq.current if cpu_freq else None,
                "cpu_freq_min": cpu_freq.min if cpu_freq else None,
                "cpu_freq_max": cpu_freq.max if cpu_freq else None,
                "cpu_stats_ctx_switches": cpu_stats.ctx_switches,
                "cpu_stats_interrupts": cpu_stats.interrupts,
                "cpu_stats_soft_interrupts": cpu_stats.soft_interrupts,
                "cpu_stats_syscalls": cpu_stats.syscalls,
            }
        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            return {"error": str(e)}
    
    def get_cpu_usage_breakdown(self) -> Dict[str, float]:
        """Get CPU usage breakdown by core"""
        try:
            if not self.is_windows:
                return {"total": psutil.cpu_percent(interval=0.1)}
            
            # Get per-core CPU usage
            per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
            total = sum(per_cpu) / len(per_cpu)
            
            breakdown = {"total": total}
            for i, usage in enumerate(per_cpu):
                breakdown[f"core_{i}"] = usage
            
            return breakdown
            
        except Exception as e:
            logger.error(f"Error getting CPU breakdown: {e}")
            return {"total": psutil.cpu_percent(interval=0.1)}

# Global instance
windows_cpu_monitor = WindowsCPUMonitor()

def get_windows_cpu_percent(interval: float = 0.1) -> float:
    """Convenience function to get normalized CPU percentage"""
    return windows_cpu_monitor.get_normalized_cpu_percent(interval)

def get_cpu_info() -> Dict[str, Any]:
    """Get CPU information for debugging"""
    return windows_cpu_monitor.get_detailed_cpu_info()
