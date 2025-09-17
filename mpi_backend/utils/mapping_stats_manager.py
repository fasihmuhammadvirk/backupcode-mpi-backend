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
            with open(self.stats_file_path, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, default=str, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error writing stats file: {e}")
            raise

    def _get_default_stats(self) -> Dict[str, Any]:
        """Get default statistics structure."""
        return {
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

    def update_temp_mapping_stats(self, stats: Dict[str, Any]):
        """
        Update temporary mapping statistics.

        Args:
            stats: Dictionary containing temp mapping statistics
        """
        current_stats = self._read_stats()

        # Update stats directly (flat structure)
        current_stats["temp_mapping_stats"].update(stats)
        current_stats["temp_mapping_stats"]["last_updated"] = datetime.now(
        ).isoformat()

        self._write_stats(current_stats)
        logger.info("Updated temp mapping statistics")

    def update_item_mapping_stats(self, stats: Dict[str, Any]):
        """
        Update item mapping statistics.

        Args:
            stats: Dictionary containing item mapping statistics
        """
        current_stats = self._read_stats()

        # Update stats directly (flat structure)
        current_stats["item_mapping_stats"].update(stats)
        current_stats["item_mapping_stats"]["last_updated"] = datetime.now(
        ).isoformat()

        self._write_stats(current_stats)
        logger.info("Updated item mapping statistics")

    def update_overall_stats(self, stats: Dict[str, Any]):
        """
        Update overall statistics.

        Args:
            stats: Dictionary containing overall statistics
        """
        current_stats = self._read_stats()

        # Update stats directly (flat structure)
        current_stats["overall_stats"].update(stats)

        self._write_stats(current_stats)
        logger.info("Updated overall statistics")

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
        return stats.get("temp_mapping_stats", {})

    def get_current_item_mapping_stats(self) -> Dict[str, Any]:
        """Get current item mapping statistics only."""
        stats = self._read_stats()
        return stats.get("item_mapping_stats", {})

    def get_current_overall_stats(self) -> Dict[str, Any]:
        """Get current overall statistics only."""
        stats = self._read_stats()
        return stats.get("overall_stats", {})

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
            current_stats["overall_stats"]["last_full_sync"] = (
                timestamp.isoformat()
            )
        elif operation == "uidi_update":
            current_stats["overall_stats"]["last_uidi_update"] = (
                timestamp.isoformat()
            )
        elif operation == "all_update":
            current_stats["overall_stats"]["last_all_update"] = (
                timestamp.isoformat()
            )
        elif operation == "temp_sync":
            current_stats["temp_mapping_stats"]["last_sync_time"] = (
                timestamp.isoformat()
            )
        elif operation == "item_sync":
            current_stats["item_mapping_stats"]["last_sync_time"] = (
                timestamp.isoformat()
            )

        self._write_stats(current_stats)
        logger.info(f"Updated sync time for operation: {operation}")

    def reset_stats(self):
        """Reset all statistics to default values."""
        default_stats = self._get_default_stats()
        self._write_stats(default_stats)
        logger.info("Reset all mapping statistics to default values")
