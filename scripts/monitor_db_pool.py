#!/usr/bin/env python3
"""
Database Pool Monitor Script
Monitors database connection pool usage and alerts when pools are getting full.
Run this script to monitor your database pool status in real-time.
"""

import requests
import time
from datetime import datetime

# Configuration
API_BASE_URL = "http://localhost:8000"
HEALTH_ENDPOINT = f"{API_BASE_URL}/health/db-pool"
CHECK_INTERVAL = 30  # Check every 30 seconds
ALERT_THRESHOLD = 80  # Alert when usage is above 80%


def check_pool_status():
    """Check database pool status via API"""
    try:
        response = requests.get(HEALTH_ENDPOINT, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"API returned status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to API: {e}")
        return None


def format_pool_info(pool_data):
    """Format pool information for display"""
    if not pool_data or "database_pools" not in pool_data:
        return "No pool data available"
    
    pools = pool_data["database_pools"]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    info = f"\n=== Database Pool Status ({timestamp}) ===\n"
    info += f"Overall Status: {pool_data['status'].upper()}\n\n"
    
    if "main_pool_usage" in pools:
        info += f"Main Pool: {pools['main_pool_usage']:.1f}% "
        info += f"({pools['main_checked_out']}/{pools['main_pool_size']})\n"
        
    if "qb_pool_usage" in pools:
        info += f"QB Pool:   {pools['qb_pool_usage']:.1f}% "
        info += f"({pools['qb_checked_out']}/{pools['qb_pool_size']})\n"
    
    return info


def should_alert(pool_data):
    """Check if we should send an alert"""
    if not pool_data or "database_pools" not in pool_data:
        return False
    
    pools = pool_data["database_pools"]
    
    # Check main pool
    if "main_pool_usage" in pools and pools["main_pool_usage"] > ALERT_THRESHOLD:
        return True
    
    # Check QB pool
    if "qb_pool_usage" in pools and pools["qb_pool_usage"] > ALERT_THRESHOLD:
        return True
    
    return False


def main():
    """Main monitoring loop"""
    print("🚀 Starting Database Pool Monitor...")
    print(f"📡 Monitoring: {HEALTH_ENDPOINT}")
    print(f"⏰ Check Interval: {CHECK_INTERVAL} seconds")
    print(f"🚨 Alert Threshold: {ALERT_THRESHOLD}%")
    print("=" * 50)
    
    try:
        while True:
            pool_data = check_pool_status()
            
            if pool_data:
                # Display current status
                print(format_pool_info(pool_data))
                
                # Check for alerts
                if should_alert(pool_data):
                    print("🚨 ALERT: Database pool usage is high!")
                    print("   Consider checking for connection leaks.")
                
                # Display overall health
                status = pool_data.get("status", "unknown")
                if status == "healthy":
                    print("✅ Pool status: HEALTHY")
                elif status == "warning":
                    print("⚠️  Pool status: WARNING")
                else:
                    print("❌ Pool status: UNHEALTHY")
                
            else:
                print(f"❌ Failed to get pool status at {datetime.now()}")
            
            print("-" * 50)
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"💥 Unexpected error: {e}")


if __name__ == "__main__":
    main()
