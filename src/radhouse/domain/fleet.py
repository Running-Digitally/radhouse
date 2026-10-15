"""Executable opt-in guest contract; transport liveness never supplies identity."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$')]


class RuntimeDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    contract: Literal['radhouse-runtime-v1']
    bot_id: Identifier
    profile: Identifier
    runtime_revision: Identifier
    provider_binding: Identifier
    result_protocol: Literal['work-result-v1']
    observations: Literal['durable-sequence-v1']
    durable_runs: Literal[True]
    durable_workspace: Literal[True]
    admission: Literal['ready', 'held', 'unavailable']
    hold_reason: Literal['maintenance', 'manual_stop', 'storage_pressure', 'model_unavailable', 'runtime_upgrade'] | None
    max_parallel_runs: Annotated[int, Field(ge=1, le=16)]
    observed_at: Annotated[int, Field(ge=1)]
    guidance_receipts: bool

    @model_validator(mode='before')
    @classmethod
    def literal_boolean_claims(cls, value):
        if isinstance(value, dict) and any(value.get(name) is not True
                for name in ('durable_runs', 'durable_workspace')):
            raise ValueError('durable_runtime_evidence_required')
        return value

    @model_validator(mode='after')
    def coherent_hold(self):
        if (self.admission == 'ready') != (self.hold_reason is None):
            raise ValueError('invalid_admission_hold')
        return self
