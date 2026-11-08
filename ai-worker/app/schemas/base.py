"""Consistent JSON names for engine library contracts."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class EngineSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", allow_inf_nan=False
    )
