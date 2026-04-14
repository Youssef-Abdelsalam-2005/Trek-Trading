import asyncio
import signal
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [engine] %(message)s")
log = logging.getLogger(__name__)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("Execution engine started — monitoring loop active")
    while not stop.is_set():
        await asyncio.wait_for(stop.wait(), timeout=5.0)
    log.info("Execution engine shutting down")


if __name__ == "__main__":
    asyncio.run(main())
