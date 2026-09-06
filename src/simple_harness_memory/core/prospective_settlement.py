"""Typed invalidation dependency or independently persisted no-object terminal."""
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from collections.abc import Mapping
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.mutation_receipts import _identifier, _digest
from simple_harness_memory.core.operation_audit import _hash
from simple_harness_memory.core.occurrence import OutboxEntryV1


def _time(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise MemoryValidationError('prospective_settlement_time_invalid')
    return float(value)


def _plain(value):
    if isinstance(value,Mapping): return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,tuple): return [_plain(v) for v in value]
    return value


def _freeze(value):
    if isinstance(value,Mapping): return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if isinstance(value,(list,tuple)): return tuple(_freeze(v) for v in value)
    return value

@dataclass(frozen=True,slots=True)
class _CancellationIdentity:
    deployment_id: str
    household_id: str
    subject: str
    outbox_id: str
    outbox_payload_hash: str
    outbox_created_at: float
    memory_id: str
    target_revision: int
    registration_revision: int
    trigger_hash: str
    target_source_hash: str

    def __post_init__(self):
        for key in ('deployment_id','household_id','subject','outbox_id','memory_id'):
            _identifier(getattr(self,key),key)
        for key in ('outbox_payload_hash','trigger_hash','target_source_hash'):
            _digest(getattr(self,key),key)
        if (type(self.target_revision) is not int or self.target_revision<1
            or type(self.registration_revision) is not int or self.registration_revision!=self.target_revision):
            raise MemoryValidationError('prospective_settlement_revision_invalid')
        object.__setattr__(self,'outbox_created_at',_time(self.outbox_created_at))

    def to_json(self):
        return {key:_plain(getattr(self,key)) for key in self.__dataclass_fields__
            if key not in {'receipt_hash','source_hash','operation_observation','registration_entry'}}

@dataclass(frozen=True,slots=True)
class RegistrationRequiredView(_CancellationIdentity):
    registration_entry: OutboxEntryV1
    kind: str = 'registration_required'
    schema_version: int = 1
    source_hash: str = field(init=False)
    operation_observation: object | None = field(default=None,compare=False,repr=False)

    def __post_init__(self):
        _CancellationIdentity.__post_init__(self)
        if self.kind!='registration_required' or type(self.schema_version) is not int or self.schema_version!=1:
            raise MemoryValidationError('prospective_registration_required_kind_invalid')
        entry=self.registration_entry
        if type(entry) is not OutboxEntryV1 or entry.topic!='memory.prospective.registration.requested':
            raise MemoryValidationError('prospective_registration_dependency_invalid')
        payload=entry.payload
        if (payload is None or payload.get('command')!='registration' or payload.get('memory_id')!=self.memory_id
            or payload.get('prospective_revision')!=self.target_revision
            or payload.get('registration_revision')!=self.registration_revision
            or payload.get('trigger_hash')!=self.trigger_hash):
            raise MemoryValidationError('prospective_registration_dependency_identity_differs')
        from dataclasses import replace
        object.__setattr__(self,'registration_entry',replace(entry,payload=_freeze(payload)))
        object.__setattr__(self,'source_hash',_hash('memory.prospective.invalidation.required.v1',self.to_json()))

    def to_json(self):
        return {**_CancellationIdentity.to_json(self),'registration_entry':{
            key:_plain(getattr(self.registration_entry,key)) for key in self.registration_entry.__dataclass_fields__}}

@dataclass(frozen=True,slots=True)
class ProspectiveInvalidationNotRequiredReceipt(_CancellationIdentity):
    receipt_id: str
    signal_result_id: str
    signal_result_hash: str
    checked_at: float
    kind: str = 'not_required'
    reason: str = 'signal_revision_never_registration_requested'
    schema_version: int = 1
    receipt_hash: str = field(init=False)
    operation_observation: object | None = field(default=None,compare=False,repr=False)

    def __post_init__(self):
        _CancellationIdentity.__post_init__(self)
        if (self.kind!='not_required' or self.reason!='signal_revision_never_registration_requested'
            or type(self.schema_version) is not int or self.schema_version!=1):
            raise MemoryValidationError('prospective_settlement_receipt_kind_invalid')
        _identifier(self.receipt_id,'receipt_id');_identifier(self.signal_result_id,'signal_result_id')
        _digest(self.signal_result_hash,'signal_result_hash')
        object.__setattr__(self,'checked_at',_time(self.checked_at))
        object.__setattr__(self,'receipt_hash',_hash('memory.prospective.invalidation.not-required.receipt.v1',self.to_json()))

    @classmethod
    def from_json(cls,value):
        if type(value) is not dict or set(value)!={key for key in cls.__dataclass_fields__ if key not in {'receipt_hash','operation_observation'}}:
            raise MemoryValidationError('prospective_settlement_receipt_wire_invalid')
        return cls(**value)
