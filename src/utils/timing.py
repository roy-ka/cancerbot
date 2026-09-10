"""Per-stage timing for the generate-answer flow (src/routers/conversations.py,
src/routers/conversation_helper.py), logged through the standard `logging`
pipeline so it reaches Axiom the same way every other log line does (see
src/main.py:_init_axiom_logging) — no separate metrics client needed.

`extra={"stage": ..., "took_ms": ...}` lands as first-class fields on the
Axiom record (axiom_py.logging.AxiomHandler ships `record.__dict__` as-is),
not just text inside `msg` — so a stage's duration is directly queryable/
aggregatable in Axiom instead of needing to parse it out of a message string.
"""
import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def timed_stage(stage: str, **extra):
    """Wrap one step of the flow; logs its wall-clock duration on exit,
    success or failure alike (a stage that's about to raise is exactly the
    one worth knowing the duration of)."""
    t0 = time.time()
    try:
        yield
    finally:
        took_ms = int((time.time() - t0) * 1000)
        logger.info(
            "[timing] stage=%s took_ms=%dms", stage, took_ms,
            extra={"stage": stage, "took_ms": took_ms, **extra},
        )
