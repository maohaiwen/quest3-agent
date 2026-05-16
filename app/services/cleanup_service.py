"""Data cleanup service — removes expired sessions and orphaned data.

Runs periodically in the background:
- Deletes sessions older than SESSION_RETENTION_DAYS (default 90)
- Cascade-deletes related messages, memory (FK ON DELETE CASCADE)
- Cleans orphaned ChromaDB collections
"""
import asyncio
import logging
from typing import Optional

from app.database.connection import DatabaseConnection
from app.utils.timezone import beijing_now

logger = logging.getLogger(__name__)


class CleanupService:
    """Background service that periodically purges expired data."""

    def __init__(self, db: DatabaseConnection, retention_days: int = 90):
        self._db = db
        self._retention_days = retention_days
        self._task: Optional[asyncio.Task] = None

    async def run_once(self) -> dict:
        """Execute a single cleanup pass.

        Returns:
            Summary dict with counts of deleted items.
        """
        cutoff = beijing_now()
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=self._retention_days)
        cutoff_str = cutoff.isoformat()

        summary = {"sessions_deleted": 0, "errors": []}

        try:
            # Count sessions to delete
            count_row = await self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM sessions WHERE updated_at < ?",
                (cutoff_str,),
            )
            to_delete = count_row["cnt"] if count_row else 0

            if to_delete == 0:
                logger.info("Data cleanup: no expired sessions found")
                return summary

            # Delete expired sessions (CASCADE handles messages, memory)
            await self._db.execute(
                "DELETE FROM sessions WHERE updated_at < ?",
                (cutoff_str,),
            )
            await self._db.commit()
            summary["sessions_deleted"] = to_delete
            logger.info(f"Data cleanup: deleted {to_delete} expired sessions (older than {cutoff_str})")

        except Exception as e:
            logger.error(f"Data cleanup error: {e}", exc_info=True)
            summary["errors"].append(str(e))

        return summary

    async def _run_loop(self, interval_hours: int) -> None:
        """Background loop that runs cleanup at regular intervals."""
        # Run once immediately on start
        try:
            await self.run_once()
        except Exception as e:
            logger.error(f"Initial data cleanup failed: {e}", exc_info=True)

        # Then periodically
        while True:
            await asyncio.sleep(interval_hours * 3600)
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Periodic data cleanup failed: {e}", exc_info=True)

    def start(self, interval_hours: int = 24) -> None:
        """Start the background cleanup task.

        Args:
            interval_hours: Hours between cleanup runs.
        """
        self._task = asyncio.create_task(self._run_loop(interval_hours))
        logger.info(f"Data cleanup task scheduled (retention={self._retention_days}d, interval={interval_hours}h)")

    def stop(self) -> None:
        """Cancel the background cleanup task."""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("Data cleanup task cancelled")


# Global instance (initialized during app startup)
cleanup_service: Optional[CleanupService] = None
