"""
app/ai_clients/groq_client.py

Hybrid text-LLM routing (Section 8.2). Llama 3.1 8B is the default model;
Llama 3.3 70B is used selectively for tasks that benefit from a larger model
(here: course-level precomputation flagged as complex). Logs every call to
ModelUsageLog (Section 8.2's "log which application/model/feature") so the
shared Groq budget (Section 20.7) can be monitored across the Admin App and
the Client App.

Both applications should import THIS file as a shared internal package
(Section 15.1) rather than duplicating the client.
"""
import json
import time
from typing import Literal

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()

_client = AsyncGroq(api_key=settings.GROQ_API_KEY)

ModelTier = Literal["default", "escalation"]


def _resolve_model(tier: ModelTier) -> str:
    return settings.GROQ_MODEL_DEFAULT if tier == "default" else settings.GROQ_MODEL_ESCALATION


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
async def generate_text(
    *,
    system_prompt: str,
    user_prompt: str,
    tier: ModelTier = "default",
    feature: str,
    application: Literal["admin", "client"] = "admin",
    lecture_id: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    json_mode: bool = False,
) -> str:
    """
    Single grounded text-generation call. Returns raw text (or a JSON string
    if json_mode=True — caller is responsible for json.loads()).

    `feature` should be a dotted label like "precompute.chapters" or
    "explain.followup_decision" so usage logs are attributable (Section 8.2).
    """
    model = _resolve_model(tier)
    started = time.monotonic()

    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = await _client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )

    latency_ms = int((time.monotonic() - started) * 1000)
    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)

    logger.info(
        f"groq_call feature={feature} model={model} tier={tier} "
        f"latency_ms={latency_ms} "
        f"prompt_tokens={getattr(usage, 'prompt_tokens', None)} "
        f"completion_tokens={getattr(usage, 'completion_tokens', None)}"
    )

    # Caller decides whether/how to persist a ModelUsageLog row — see
    # app/services/precompute_service.py for the pattern (keeps this client
    # free of a DB dependency, so it can be imported by the Client App too).
    return content, {
        "model": model,
        "latency_ms": latency_ms,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
    }


async def generate_structured(
    *,
    system_prompt: str,
    user_prompt: str,
    tier: ModelTier = "default",
    feature: str,
    application: Literal["admin", "client"] = "admin",
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> tuple[dict, dict]:
    """
    Convenience wrapper for the Section 8.8 agentic-decision pattern: forces
    JSON-mode output and parses it, so callers get a Python dict back instead
    of having to json.loads() themselves. Used by the Client App's
    followup_service.py; included here since both apps share this module.
    """
    raw, meta = await generate_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tier=tier,
        feature=feature,
        application=application,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"groq_structured_parse_failed feature={feature} raw={raw[:200]}")
        parsed = {}
    return parsed, meta


async def describe_image(
    *,
    image_url: str,
    prompt: str,
    feature: str,
) -> tuple[str, dict]:
    """
    Vision LLM call (Section 8.3) — used when OCR confidence is insufficient
    (Section 20.5: prefer OCR first, escalate only when needed).
    """
    started = time.monotonic()
    response = await _client.chat.completions.create(
        model=settings.GROQ_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        max_tokens=1024,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    content = response.choices[0].message.content or ""
    logger.info(f"groq_vision_call feature={feature} latency_ms={latency_ms}")
    return content, {"model": settings.GROQ_VISION_MODEL, "latency_ms": latency_ms}
