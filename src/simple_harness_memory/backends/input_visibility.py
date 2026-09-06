"""Bounded item-level request input using existing evidence/suppression authority.

Host authority is fetched outside Memory's transaction. The source and reverse
suppression check uses one current SQLite snapshot. Ordinary history is unchanged.
"""
from __future__ import annotations
import hashlib
from dataclasses import asdict

from simple_harness import DisclosureContext
from simple_harness.runtime import (
    EvidenceSpanRef, EvidenceActorRole, EvidenceProvenance, EvidenceSupportKind,
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1, verify_evidence_span,
)
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.errors import MemoryOwnershipConflict
from simple_harness_memory.core.evidence import validate_sanitized_evidence
from simple_harness_memory.core.history import history_hash
from simple_harness_memory.core.input_visibility import (
    CurrentInputBindingV1, CurrentInputAuthorityV1, CurrentInputVisibilityV1, current_input_request_hash,
)
from simple_harness_memory.backends.history_source_guard import (
    history_source_operation,
)


class _ResolvedItem:
    def __init__(self, admitted):
        self.admitted = admitted

    async def resolve_admitted_evidence(self, span):
        return self.admitted


def _span(envelope, receipt):
    payload = envelope.sanitized_payload
    if (envelope.source_kind.value != "user_message" or envelope.evidence_refs
            or set(payload) != {"schema_version", "delivery_key", "text"}
            or type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or envelope.source_ref != "foreground-turn:" + payload["delivery_key"]):
        raise ValueError("current_input_whole_user_item_required")
    text = payload["text"]
    if type(text) is not str or not text:
        raise ValueError("current_input_text_invalid")
    return EvidenceSpanRef(
        span_id="current-input:" + envelope.evidence_id,
        evidence_id=envelope.evidence_id, envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash, admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash, source_kind=envelope.source_kind,
        item_ordinal=1, item_id=payload["delivery_key"], item_json_pointer="/text",
        start_byte=0, end_byte=len(text.encode()), exact_quote=text,
        quote_hash=hashlib.sha256(text.encode()).hexdigest(), source_hash=envelope.source_hash,
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
        actor_role=EvidenceActorRole.USER, provenance=EvidenceProvenance.AUTHENTICATED_USER,
        support_kind=EvidenceSupportKind.EXPLICIT_USER_ASSERTION, typed_observation=None,
    )


@history_source_operation
async def check_current_input_visibility(backend, *, principal, disclosure_context, binding, bindings=None):
    if (type(principal) is not MemoryPrincipal or type(disclosure_context) is not DisclosureContext
            or type(binding) is not CurrentInputBindingV1):
        raise TypeError("current_input_canonical_types_required")
    context = DisclosureContext.from_json(disclosure_context.to_json())
    if principal.actor_id != context.subject or binding.evidence.envelope.subject != principal.actor_id:
        raise MemoryOwnershipConflict("current_input_subject_mismatch")
    if (context.source.value != "authenticated_host" or context.trust.value != "trusted_authority"
            or context.generation.value != "current" or context.purpose.value != "task_execution"
            or "unknown" in {context.recipient.value, context.intended_audience.value}):
        raise ValueError("current_input_context_invalid")
    validate_sanitized_evidence(binding.evidence.envelope, binding.evidence.receipt,
        supported_filter_policies=backend._supported_filter_policies)
    span = _span(binding.evidence.envelope, binding.evidence.receipt)
    request_hash = current_input_request_hash(principal, context, binding, bindings)
    port = backend._current_input_authority
    if port is None:
        raise ValueError("current_input_authority_unavailable")
    # This new use boundary requires a real public owner registration, including
    # deployment and household. Ordinary history's cold placeholder rule is not a grant.
    if backend._db is None or backend._receipt is None:
        raise RuntimeError("human-memory v7 backend is not initialized")
    async with backend._write_lock:
        await backend._authorize_short_horizon_principal_unlocked(principal)
    # No external Host callbacks while holding Memory SQLite's read/write lock.
    authority = await port.resolve_current_input(principal=principal, disclosure_context=context, binding=binding)
    reason = "current_input_authority_unverifiable"
    if authority is not None:
        if (type(authority) is not CurrentInputAuthorityV1 or authority.binding_hash != binding.binding_hash
                or authority.disclosure_context != context
                or authority.admitted.envelope != binding.evidence.envelope
                or authority.admitted.receipt != binding.evidence.receipt):
            raise ValueError("current_input_authority_binding_mismatch")
        if authority.principal != principal:
            raise MemoryOwnershipConflict("current_input_authority_principal_mismatch")
        origin = authority.origin
        if (origin.namespace.subject != principal.actor_id or origin.proof_kind != "atomic"
                or origin.evidence_id != span.evidence_id or origin.envelope_hash != span.envelope_hash
                or origin.admission_receipt_id != span.admission_receipt_id
                or origin.admission_receipt_hash != span.admission_receipt_hash):
            raise ValueError("current_input_origin_mismatch")
        item = await verify_evidence_span(span, _ResolvedItem(authority.admitted))
        expected = "personal" if authority.declaration_kind == "current_user" else "public"
        if item.required_privacy_class.value != expected or item.required_information_attributes:
            raise ValueError("current_input_classification_mismatch")
        reason = "current_input_visible"
    from simple_harness_memory.backends.history_visibility import check_history_visibility
    checked_bindings = (binding.evidence,) if bindings is None else bindings
    if type(checked_bindings) is not tuple or binding.evidence not in checked_bindings:
        raise ValueError("current_input_batch_missing_exact_item")
    snapshot = await check_history_visibility(backend, principal=principal, disclosure_context=context,
        bindings=checked_bindings, _require_principal_binding=True,
        _current_input=None if authority is None else (binding.evidence, authority.authority_hash))
    exact_hash = history_hash("memory.history.binding.v1", binding.evidence.to_json())
    source = next(item for item in snapshot.items if item.binding_hash == exact_hash)
    if authority is not None:
        reason = "current_input_visible" if source.visible else source.reason
    return CurrentInputVisibilityV1(binding.binding_hash,
        request_hash,
        snapshot.checked_at, snapshot.authority_epoch, snapshot.policy_hash,
        reason == "current_input_visible", reason,
        None if authority is None else authority.declaration_kind,
        None if authority is None else authority.authority_hash, history_visibility=snapshot)
