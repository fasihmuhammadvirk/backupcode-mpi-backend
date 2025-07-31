import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class MappingStatsManager:
    """Manager for mapping statistics JSON file."""

    def __init__(self, stats_file_path: str = None):
        """
        Initialize the stats manager.

        Args:
            stats_file_path: Path to the statistics JSON file
        """
        if stats_file_path is None:
            # Default path relative to this file
            current_dir = Path(__file__).parent
            stats_file_path = current_dir.parent / \
                "storage" / "fixtures" / "mapping_stats.json"

        self.stats_file_path = Path(stats_file_path)
        self._ensure_stats_file_exists()

    def _ensure_stats_file_exists(self):
        """Ensure the statistics file exists with default structure."""
        if not self.stats_file_path.exists():
            self.stats_file_path.parent.mkdir(parents=True, exist_ok=True)
            default_stats = {
                "temp_mapping_stats": {
                    "total_mappings": 0,
                    "unique_sheets": 0,
                    "sheet_names": [],
                    "mappings_per_sheet": {},
                    "last_updated": None,
                    "last_sync_time": None
                },
                "item_mapping_stats": {
                    "total_mappings": 0,
                    "unique_sheets": 0,
                    "sheet_names": [],
                    "mappings_per_sheet": {},
                    "permanent_mappings": 0,
                    "temporary_mappings": 0,
                    "invalid_mappings": 0,
                    "last_updated": None,
                    "last_sync_time": None
                },
                "overall_stats": {
                    "total_items": 0,
                    "total_sheets_processed": 0,
                    "last_full_sync": None,
                    "last_uidi_update": None,
                    "last_all_update": None
                }
            }
            self._write_stats(default_stats)
            logger.info(
                f"Created new mapping stats file at {self.stats_file_path}")

    def _read_stats(self) -> Dict[str, Any]:
        """Read statistics from JSON file."""
        try:
            with open(self.stats_file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error reading stats file: {e}")
            return self._get_default_stats()

    def _write_stats(self, stats: Dict[str, Any]):
        """Write statistics to JSON file."""
        try:
            with open(self.stats_file_path, 'w') as f:
                json.dump(stats, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error writing stats file: {e}")
            raise

    def _get_default_stats(self) -> Dict[str, Any]:
        """Get default statistics structure."""
        return {
            "temp_mapping_stats": {
                "current": {
                    "total_mappings": 0,
                    "unique_sheets": 0,
                    "sheet_names": [],
                    "mappings_per_sheet": {},
                    "last_updated": None,
                    "last_sync_time": None
                },
                "previous": {
                    "total_mappings": 0,
                    "unique_sheets": 0,
                    "sheet_names": [],
                    "mappings_per_sheet": {},
                    "last_updated": None,
                    "last_sync_time": None
                },
                "changes": {
                    "mappings_added": 0,
                    "mappings_removed": 0,
                    "net_change": 0,
                    "sheets_added": 0,
                    "sheets_removed": 0,
                    "last_change_timestamp": None
                }
            },
            "item_mapping_stats": {
                "current": {
                    "total_mappings": 0,
                    "unique_sheets": 0,
                    "sheet_names": [],
                    "mappings_per_sheet": {},
                    "permanent_mappings": 0,
                    "temporary_mappings": 0,
                    "invalid_mappings": 0,
                    "last_updated": None,
                    "last_sync_time": None
                },
                "previous": {
                    "total_mappings": 0,
                    "unique_sheets": 0,
                    "sheet_names": [],
                    "mappings_per_sheet": {},
                    "permanent_mappings": 0,
                    "temporary_mappings": 0,
                    "invalid_mappings": 0,
                    "last_updated": None,
                    "last_sync_time": None
                },
                "changes": {
                    "mappings_added": 0,
                    "mappings_removed": 0,
                    "net_change": 0,
                    "permanent_added": 0,
                    "permanent_removed": 0,
                    "temporary_added": 0,
                    "temporary_removed": 0,
                    "sheets_added": 0,
                    "sheets_removed": 0,
                    "last_change_timestamp": None
                }
            },
            "overall_stats": {
                "current": {
                    "total_items": 0,
                    "total_sheets_processed": 0,
                    "last_full_sync": None,
                    "last_uidi_update": None,
                    "last_all_update": None
                },
                "previous": {
                    "total_items": 0,
                    "total_sheets_processed": 0,
                    "last_full_sync": None,
                    "last_uidi_update": None,
                    "last_all_update": None
                },
                "changes": {
                    "items_added": 0,
                    "items_removed": 0,
                    "net_change": 0,
                    "last_change_timestamp": None
                }
            }
        }

    def update_temp_mapping_stats(self, stats: Dict[str, Any]):
        """
        Update temporary mapping statistics.

        Args:
            stats: Dictionary containing temp mapping statistics
        """
        current_stats = self._read_stats()

        # Store current stats as previous before updating
        current_stats["temp_mapping_stats"]["previous"] = current_stats["temp_mapping_stats"]["current"].copy()

        # Update current stats
        current_stats["temp_mapping_stats"]["current"].update(stats)
        current_stats["temp_mapping_stats"]["current"]["last_updated"] = datetime.now(
        ).isoformat()

        # Calculate changes
        previous = current_stats["temp_mapping_stats"]["previous"]
        current = current_stats["temp_mapping_stats"]["current"]

        current_stats["temp_mapping_stats"]["changes"] = {
            "mappings_added": max(0, current["total_mappings"] - previous["total_mappings"]),
            "mappings_removed": max(0, previous["total_mappings"] - current["total_mappings"]),
            "net_change": current["total_mappings"] - previous["total_mappings"],
            "sheets_added": max(0, current["unique_sheets"] - previous["unique_sheets"]),
            "sheets_removed": max(0, previous["unique_sheets"] - current["unique_sheets"]),
            "last_change_timestamp": datetime.now().isoformat()
        }

        self._write_stats(current_stats)
        logger.info("Updated temp mapping statistics with change tracking")

    def update_item_mapping_stats(self, stats: Dict[str, Any]):
        """
        Update item mapping statistics.

        Args:
            stats: Dictionary containing item mapping statistics
        """
        current_stats = self._read_stats()

        # Store current stats as previous before updating
        current_stats["item_mapping_stats"]["previous"] = current_stats["item_mapping_stats"]["current"].copy()

        # Update current stats
        current_stats["item_mapping_stats"]["current"].update(stats)
        current_stats["item_mapping_stats"]["current"]["last_updated"] = datetime.now(
        ).isoformat()

        # Calculate changes
        previous = current_stats["item_mapping_stats"]["previous"]
        current = current_stats["item_mapping_stats"]["current"]

        current_stats["item_mapping_stats"]["changes"] = {
            "mappings_added": max(0, current["total_mappings"] - previous["total_mappings"]),
            "mappings_removed": max(0, previous["total_mappings"] - current["total_mappings"]),
            "net_change": current["total_mappings"] - previous["total_mappings"],
            "permanent_added": max(0, current["permanent_mappings"] - previous["permanent_mappings"]),
            "permanent_removed": max(0, previous["permanent_mappings"] - current["permanent_mappings"]),
            "temporary_added": max(0, current["temporary_mappings"] - previous["temporary_mappings"]),
            "temporary_removed": max(0, previous["temporary_mappings"] - current["temporary_mappings"]),
            "sheets_added": max(0, current["unique_sheets"] - previous["unique_sheets"]),
            "sheets_removed": max(0, previous["unique_sheets"] - current["unique_sheets"]),
            "last_change_timestamp": datetime.now().isoformat()
        }

        self._write_stats(current_stats)
        logger.info("Updated item mapping statistics with change tracking")

    def update_overall_stats(self, stats: Dict[str, Any]):
        """
        Update overall statistics.

        Args:
            stats: Dictionary containing overall statistics
        """
        current_stats = self._read_stats()

        # Store current stats as previous before updating
        current_stats["overall_stats"]["previous"] = current_stats["overall_stats"]["current"].copy()

        # Update current stats
        current_stats["overall_stats"]["current"].update(stats)

        # Calculate changes
        previous = current_stats["overall_stats"]["previous"]
        current = current_stats["overall_stats"]["current"]

        current_stats["overall_stats"]["changes"] = {
            "items_added": max(0, current["total_items"] - previous["total_items"]),
            "items_removed": max(0, previous["total_items"] - current["total_items"]),
            "net_change": current["total_items"] - previous["total_items"],
            "last_change_timestamp": datetime.now().isoformat()
        }

        self._write_stats(current_stats)
        logger.info("Updated overall statistics with change tracking")

    def get_temp_mapping_stats(self) -> Dict[str, Any]:
        """Get temporary mapping statistics."""
        stats = self._read_stats()
        return stats.get("temp_mapping_stats", {})

    def get_item_mapping_stats(self) -> Dict[str, Any]:
        """Get item mapping statistics."""
        stats = self._read_stats()
        return stats.get("item_mapping_stats", {})

    def get_overall_stats(self) -> Dict[str, Any]:
        """Get overall statistics."""
        stats = self._read_stats()
        return stats.get("overall_stats", {})

    def get_current_temp_mapping_stats(self) -> Dict[str, Any]:
        """Get current temporary mapping statistics only."""
        stats = self._read_stats()
        return stats.get("temp_mapping_stats", {}).get("current", {})

    def get_current_item_mapping_stats(self) -> Dict[str, Any]:
        """Get current item mapping statistics only."""
        stats = self._read_stats()
        return stats.get("item_mapping_stats", {}).get("current", {})

    def get_current_overall_stats(self) -> Dict[str, Any]:
        """Get current overall statistics only."""
        stats = self._read_stats()
        return stats.get("overall_stats", {}).get("current", {})

    def get_temp_mapping_changes(self) -> Dict[str, Any]:
        """Get temporary mapping changes."""
        stats = self._read_stats()
        return stats.get("temp_mapping_stats", {}).get("changes", {})

    def get_item_mapping_changes(self) -> Dict[str, Any]:
        """Get item mapping changes."""
        stats = self._read_stats()
        return stats.get("item_mapping_stats", {}).get("changes", {})

    def get_overall_changes(self) -> Dict[str, Any]:
        """Get overall changes."""
        stats = self._read_stats()
        return stats.get("overall_stats", {}).get("changes", {})

    def get_all_stats(self) -> Dict[str, Any]:
        """Get all statistics."""
        return self._read_stats()

    def update_sync_times(self, operation: str,
                          timestamp: Optional[datetime] = None):
        """
        Update sync timestamps for different operations.

        Args:
            operation: Operation type ('full_sync', 'uidi_update', 
                        'all_update', 'temp_sync', 'item_sync')
            timestamp: Timestamp to set (defaults to current time)
        """
        if timestamp is None:
            timestamp = datetime.now()

        current_stats = self._read_stats()

        if operation == "full_sync":
            current_stats["overall_stats"]["current"]["last_full_sync"] = (
                timestamp.isoformat()
            )
        elif operation == "uidi_update":
            current_stats["overall_stats"]["current"]["last_uidi_update"] = (
                timestamp.isoformat()
            )
        elif operation == "all_update":
            current_stats["overall_stats"]["current"]["last_all_update"] = (
                timestamp.isoformat()
            )
        elif operation == "temp_sync":
            current_stats["temp_mapping_stats"]["current"]["last_sync_time"] = (
                timestamp.isoformat()
            )
        elif operation == "item_sync":
            current_stats["item_mapping_stats"]["current"]["last_sync_time"] = (
                timestamp.isoformat()
            )

        self._write_stats(current_stats)
        logger.info(f"Updated sync time for operation: {operation}")

    def reset_stats(self):
        """Reset all statistics to default values."""
        default_stats = self._get_default_stats()
        self._write_stats(default_stats)
        logger.info("Reset all mapping statistics to default values")
