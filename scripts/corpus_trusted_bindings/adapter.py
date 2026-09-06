"""Resolve reviewed literal spans, with no gold/setup parser or Host dispatch.

This module intentionally does not import the frozen first-layer compiler. Source
line coordinates are fixed; moved/changed inputs fail closed instead of invoking
a natural-language splitter. Changes outside pinned lines cannot supply values.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from .records import BINDINGS, POLICY

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REL = Path(
    "plans/2026-08-29-human-memory-digital-twin/quality/recall-corpus-candidate/"
    "review-zh/successor-12x20"
)
EXPECTED_IDS = ("C05-07",) + tuple(f"C12-{i:02}" for i in range(1, 21))
ALLOWED_FILES = {"05-task.md", "12-recipient-private.md", "总索引.md"}
COMMON_GAPS = (
    "VERIFIED_PRINCIPAL_ID_MISSING",
    "HOST_POLICY_CONFIGURATION_AND_AUTHORITY_RECEIPT_MISSING",
    "PUBLIC_SETUP_AND_READBACK_NOT_IMPLEMENTED",
    "HOST_TO_SDK_TO_PROVIDER_CLOCK_BINDING_NOT_IMPLEMENTED",
    "HOST_AUTHORITY_VERIFIER_NOT_IMPLEMENTED",
)


class BindingError(ValueError):
    """A reviewed source anchor or literal partition no longer matches."""


class DispatchBlocked(RuntimeError):
    """A source binding is not an authenticated runtime permission."""


@dataclass(frozen=True)
class SourceSpan:
    source_file: str
    line: int
    start_utf8: int
    end_utf8: int
    sha256: str
    text: str


@dataclass(frozen=True)
class BoundField:
    name: str
    source: SourceSpan


@dataclass(frozen=True)
class FixtureRequirements:
    """Strings are fixture requirements, not SDK enums or issued authority."""

    fields: tuple[BoundField, ...]
    common_policy: SourceSpan
    explicit_forwarding: tuple[BoundField, ...]
    missing_requirements: tuple[str, ...]
    source_kind: Literal["REVIEWED_FIXTURE_REQUIREMENTS"] = "REVIEWED_FIXTURE_REQUIREMENTS"

    @property
    def authority_receipt(self) -> None:
        return None


@dataclass(frozen=True)
class SourceBinding:
    case_id: str
    trusted_setup: FixtureRequirements
    user_message_source: SourceSpan
    source_partition: tuple[BoundField, ...]

    @property
    def current_user_message(self) -> str:
        return self.user_message_source.text

    @property
    def ready(self) -> Literal[False]:
        return False

    @property
    def dispatchable(self) -> Literal[False]:
        return False

    @property
    def executed(self) -> Literal[False]:
        return False


def _line(cache: dict[str, list[bytes]], filename: str, number: int) -> bytes:
    if filename not in ALLOWED_FILES or number < 1:
        raise BindingError("unknown source filename/line")
    try:
        return cache[filename][number - 1]
    except (KeyError, IndexError) as exc:
        raise BindingError(f"missing source line: {filename}:{number}") from exc


def _anchor(cache: dict[str, list[bytes]], filename: str, spec: dict) -> bytes:
    value = _line(cache, filename, spec["line"])
    if (sha256(value).hexdigest() != spec["sha256"]
            or value != spec["text"].encode("utf-8")):
        raise BindingError(f"source anchor changed: {filename}:{spec['line']}")
    return value


def _span(filename: str, number: int, line: bytes, spec: dict) -> SourceSpan:
    start, end = spec["start_utf8"], spec["end_utf8"]
    if not 0 <= start < end <= len(line):
        raise BindingError("source span out of bounds")
    value = line[start:end]
    if (sha256(value).hexdigest() != spec["sha256"]
            or value != spec["text"].encode("utf-8")):
        raise BindingError(f"source fragment changed: {filename}:{number}")
    return SourceSpan(filename, number, start, end, spec["sha256"], value.decode("utf-8"))


def _resolve(cache: dict[str, list[bytes]]) -> tuple[SourceBinding, ...]:
    if tuple(record["case_id"] for record in BINDINGS) != EXPECTED_IDS:
        raise BindingError("expected the fixed 21 unique IDs in review order")
    policy_line = _anchor(cache, POLICY["source_file"], POLICY["line_anchor"])
    policy = _span(POLICY["source_file"], POLICY["line_anchor"]["line"],
                   policy_line, POLICY["fragment"])
    results = []
    for record in BINDINGS:
        case_id, filename = record["case_id"], record["source_file"]
        _anchor(cache, filename, record["heading_anchor"])
        source = _anchor(cache, filename, record["input_anchor"])
        number = record["input_anchor"]["line"]
        partition, setup, users = [], [], []
        cursor = 0
        for spec in record["parts"]:
            span = _span(filename, number, source, spec)
            if span.start_utf8 != cursor:
                raise BindingError(f"{case_id}: omitted or overlapping source fragment")
            cursor = span.end_utf8
            role, name = spec["role"], spec["name"]
            field = BoundField(name, span)
            partition.append(field)
            if role == "trusted_setup":
                setup.append(field)
            elif role == "current_user_message":
                users.append(span)
            elif role != "syntax":
                raise BindingError(f"{case_id}: unknown reviewed fragment role")
        if cursor != len(source) or len(users) != 1:
            raise BindingError(f"{case_id}: incomplete input partition or duplicate user field")
        names = [field.name for field in setup]
        if tuple(names) != tuple(record["trusted_field_names"]) or len(names) != len(set(names)):
            raise BindingError(f"{case_id}: reviewed trusted fields changed")
        forwarding = tuple(BoundField(spec["name"], _span(filename, number, source, spec))
                           for spec in record["explicit_forwarding"])
        # Forwarding annotations are separately reviewed subspans of audience,
        # not duplicate owned pieces in the complete source partition.
        if forwarding:
            audience = next((field.source for field in setup
                             if field.name == "recipient_description"), None)
            if audience is None or any(not (audience.start_utf8 <= field.source.start_utf8
                                            < field.source.end_utf8 <= audience.end_utf8)
                                       for field in forwarding):
                raise BindingError(f"{case_id}: forwarding leaves audience source span")
        gaps = COMMON_GAPS + tuple(record["missing_requirements"])
        results.append(SourceBinding(case_id, FixtureRequirements(
            tuple(setup), policy, forwarding, gaps
        ), users[0], tuple(partition)))
    return tuple(results)


def bind_reviewed_sources(source: Path) -> tuple[SourceBinding, ...]:
    """Read only fixed anchors/spans; do not derive any value from gold or setup.

    Whole-member hashes remain the FIRST layer's unchanged responsibility. This
    adapter pins relevant line/fragment hashes so same-line gold/setup edits do
    not affect bindings. Line insertion/deletion or changed input/policy fails
    closed; no search or inferred relocation is attempted.
    """
    cache: dict[str, list[bytes]] = {}
    for filename in sorted(ALLOWED_FILES):
        path = source / filename
        if path.is_symlink():
            raise BindingError(f"symlink source not supported: {filename}")
        # Keep CR bytes so newline-convention changes fail against the pinned line.
        cache[filename] = path.read_bytes().split(b"\n")
    return _resolve(cache)


def fixture_plan(binding: SourceBinding) -> dict:
    """Coordinator-only preview. Never send this envelope to the Provider."""
    if type(binding) is not SourceBinding:
        raise TypeError("expected SourceBinding")
    return {
        "case_id": binding.case_id,
        "current_user_message": binding.current_user_message,
        "trusted_setup": {
            "source_kind": binding.trusted_setup.source_kind,
            "fields": {field.name: field.source.text for field in binding.trusted_setup.fields},
            "common_policy_text": binding.trusted_setup.common_policy.text,
            "explicit_forwarding": {field.name: field.source.text
                                    for field in binding.trusted_setup.explicit_forwarding},
            "authority_receipt": None,
        },
        "ready": False, "dispatchable": False, "executed": False,
        "missing_requirements": list(binding.trusted_setup.missing_requirements),
    }


def require_dispatch_authorization(binding: SourceBinding, receipt: object = None) -> None:
    """Fail closed even for a supplied 'receipt': no Host verifier exists here."""
    if type(binding) is not SourceBinding:
        raise TypeError("expected SourceBinding")
    raise DispatchBlocked("Host public setup/authority verifier is not implemented; dispatch denied")
