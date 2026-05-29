from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class LLMMessage:
    role: str  # 'system' | 'user' | 'assistant'
    content: str


@dataclass(slots=True)
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    async def call(
        self,
        *,
        operation: str,
        request_id: str,
        messages: list[LLMMessage],
        model: str | None = None,
    ) -> LLMResponse: ...


class InMemoryLLMClient:
    """Deterministic in-process stub.

    Echoes the last 'user' message uppercased so tests can assert exact bodies.
    Tests can set ``raise_on_call`` to a non-None exception to simulate
    provider failure; ``call_count`` exposes invocation count.
    """

    def __init__(self) -> None:
        self.call_count: int = 0
        self.raise_on_call: Exception | None = None

    async def call(
        self,
        *,
        operation: str,
        request_id: str,
        messages: list[LLMMessage],
        model: str | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        if self.raise_on_call is not None:
            raise self.raise_on_call
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )
        out = last_user.upper()
        return LLMResponse(
            content=out,
            input_tokens=sum(len(m.content) for m in messages),
            output_tokens=len(out),
        )
