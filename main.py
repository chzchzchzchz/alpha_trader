#!/usr/bin/env python3
"""
Alpha Trader - Main entry point
"""
import os
import sys
import time
import signal
import logging
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from core.settings import get_settings, load_dotenv
from core.metrics import MetricsServer, metrics
from core.trading_system import TradingSystem

def setup_signal_handlers(trading_system):
    """Setup graceful shutdown on signals"""
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down gracefully...")
        trading_system.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def main():
    """Main entry point"""
    # Load environment variables
    load_dotenv()

    # Get settings and validate
    try:
        settings = get_settings()
        print(f"Starting Alpha Trader in {settings.env} mode")
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, settings.logging.level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(settings.logging.file),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger('main')

    # Start metrics server
    metrics_server = MetricsServer(port=8000)
    try:
        metrics_server.start()
        logger.info("Metrics server started on port 8000")
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")
        # Continue without metrics in development
        if settings.env == 'production':
            sys.exit(1)

    # Initialize and start trading system
    trading_system = TradingSystem(settings)
    setup_signal_handlers(trading_system)

    try:
        if len(sys.argv) > 1 and sys.argv[1] == 'backtest':
            logger.info("Starting backtest mode")
            trading_system.run_backtest()
        else:
            logger.info("Starting live trading mode")
            trading_system.run_live()
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Trading system error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        trading_system.stop()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    main()
