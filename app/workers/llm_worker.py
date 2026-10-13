"""
app/workers/llm_worker.py — Section 15.3
Standalone-callable wrapper that routes precomputation jobs through the
shared Groq hybrid client (Section 8.2). app/services/precompute_service.py
calls groq_client directly today (see worker_queue.py note); this module
exists so precomputation can be dispatched to its own queue/process later
without changing precompute_service.py's call sites.
"""
from app.ai_clients.groq_client import generate_structured, generate_text
from app.core.logging import logger


async def process_text_job(**kwargs) -> tuple[str, dict]:
    logger.info(f"llm_worker_text_job feature={kwargs.get('feature')}")
    return await generate_text(**kwargs)


async def process_structured_job(**kwargs) -> tuple[dict, dict]:
    logger.info(f"llm_worker_structured_job feature={kwargs.get('feature')}")
    return await generate_structured(**kwargs)
