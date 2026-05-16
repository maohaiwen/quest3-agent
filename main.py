"""Quest3 Agent Application Entry Point"""
import uvicorn
import logging

from app.config import settings
from app.core.logging import setup_logging

# Configure logging
setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for the application"""
    logger.info("Starting Quest3 Agent...")

    try:
        uvicorn.run(
            "app.main:app",
            host=settings.APP_HOST,
            port=settings.APP_PORT,
            reload=settings.APP_DEBUG,
            log_level=settings.LOG_LEVEL.lower()
        )
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Error starting application: {e}")
        raise


if __name__ == "__main__":
    main()
