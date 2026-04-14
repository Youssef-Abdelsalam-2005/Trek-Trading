import asyncio
import signal
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [signer] %(message)s")
log = logging.getLogger(__name__)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("Signer started — awaiting sign requests")
    await stop.wait()
    log.info("Signer shutting down")


if __name__ == "__main__":
    asyncio.run(main())
