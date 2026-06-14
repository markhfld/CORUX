"""Thin Anthropic wrapper.

One place to construct the client and run a structured-output call. Every agent
uses `parse_structured(...)`, which constrains the response to a Pydantic model
via the Messages API structured-output support and returns the validated object.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Optional, Type, TypeVar

import anthropic
from pydantic import BaseModel

from . import config, tracing

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    # Resolves ANTHROPIC_API_KEY (or an `ant` profile) from the environment.
    return anthropic.Anthropic()


def parse_structured(
    *,
    system: str,
    user: str,
    schema: Type[T],
    step: str,
    extra_tools: Optional[list[dict]] = None,
) -> T:
    """Call Claude and return an instance of `schema`.

    `step` keys into config.EFFORT / config.MAX_TOKENS. Adaptive thinking is on
    so the model decides how much to reason per call.
    """
    client = get_client()
    kwargs: dict = {
        "model": config.MODEL,
        "max_tokens": config.MAX_TOKENS.get(step, 8000),
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": config.EFFORT.get(step, "high")},
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_format": schema,
    }
    if extra_tools:
        kwargs["tools"] = extra_tools

    effort = config.EFFORT.get(step, "high")
    tracing.emit("llm", step=step, model=config.MODEL, effort=effort, status="started")

    t0 = time.perf_counter()
    response = client.messages.parse(**kwargs)
    duration_ms = round((time.perf_counter() - t0) * 1000)

    usage = getattr(response, "usage", None)
    tracing.emit(
        "llm",
        step=step,
        model=config.MODEL,
        effort=effort,
        status="completed",
        duration_ms=duration_ms,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        request_id=getattr(response, "_request_id", None),
    )
    return response.parsed_output
