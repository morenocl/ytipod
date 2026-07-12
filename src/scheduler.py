import datetime as dt
import logging
import time

import config
import scanner
from logging_config import setup_logging

logger = logging.getLogger(__name__)


def _next_run(now=None):
    now = now or dt.datetime.now()
    hour, minute = [int(part) for part in config.DAILY_RUN_TIME.split(":", 1)]
    run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run_at <= now:
        run_at += dt.timedelta(days=1)
    return run_at


def run_forever():
    setup_logging("scheduler")
    while True:
        run_at = _next_run()
        seconds = max(1, int((run_at - dt.datetime.now()).total_seconds()))
        logger.info("Proxima ejecucion: %s", run_at.isoformat(timespec="minutes"))
        time.sleep(seconds)
        scanner.main(configure_logging=False)


if __name__ == "__main__":
    run_forever()
