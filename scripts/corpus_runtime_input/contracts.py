"""Runtime input types deliberately have no setup, class, or oracle dependency."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo


class CorpusError(ValueError):
    """Unsupported or inconsistent authored source; never repair from gold."""


@dataclass(frozen=True)
class ScenarioClock:
    instant: str
    timezone: str

    def __post_init__(self) -> None:
        instant = datetime.fromisoformat(self.instant)
        if instant.tzinfo is None:
            raise CorpusError("scenario_clock must include an explicit UTC offset")
        if instant.astimezone(ZoneInfo(self.timezone)).utcoffset() != instant.utcoffset():
            raise CorpusError("scenario_clock offset disagrees with timezone")


@dataclass(frozen=True)
class RecentMessage:
    ordinal: int
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class InitialInput:
    """Authored input plan, NOT a Provider request or an authority receipt.

    Unresolved mixed text is retained separately and cannot become a user/system
    message through this module. Clock is a fixture requirement for all three
    runtime layers; it is not an answer-bearing system prompt.
    """

    scenario_clock: ScenarioClock
    recent_messages: tuple[RecentMessage, ...]
    current_user_message: str | None
    unresolved_source_text: str | None = None


@dataclass(frozen=True)
class ScriptedFollowup:
    followup_id: str
    after_event: str
    fixture_action: str
    user_message: str
    on_unmet: str


def project_authored_conversation(value: InitialInput) -> list[dict[str, str]]:
    """Pure conversation projection for later noninterference acceptance.

    This is NOT runtime authorization: it does not establish real recent history,
    trusted policy, SDK clock, or seed readiness. No caller may use it as proof
    those public adapters exist. This module has no Provider dispatch capability.
    """
    if type(value) is not InitialInput:
        raise TypeError("expected InitialInput only")
    if value.unresolved_source_text is not None or not value.current_user_message:
        raise CorpusError("explicit trusted-context/user split is not implemented")
    if tuple(m.ordinal for m in value.recent_messages) != tuple(
        range(1, len(value.recent_messages) + 1)
    ):
        raise CorpusError("recent_messages ordinal sequence is invalid")
    messages: list[dict[str, str]] = []
    for message in value.recent_messages:
        if message.role not in ("user", "assistant") or not message.content:
            raise CorpusError("invalid recent_messages role/content")
        messages.append({"role": message.role, "content": message.content})
    messages.append({"role": "user", "content": value.current_user_message})
    return messages
