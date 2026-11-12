"""Ingestion worker entry point.

Placeholder: the Swiftly polling loop is added in build step 3.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("worker")


async def run() -> None:
    log.info("worker started (polling not implemented yet)")
    while True:
        await asyncio.sleep(60)
        log.info("worker idle")


if __name__ == "__main__":
    asyncio.run(run())
