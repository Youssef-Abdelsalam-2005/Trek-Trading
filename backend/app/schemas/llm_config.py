from pydantic import Field, SecretStr

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class LLMConfigCreate(BaseSchema):
    label: str = Field(default="default", max_length=64)
    provider: str = Field(..., max_length=64)
    model_name: str = Field(..., max_length=128)
    api_base_url: str | None = Field(default=None, max_length=512)
    api_key: SecretStr
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1)
    cost_per_input_token: float = Field(default=0.0, ge=0.0)
    cost_per_output_token: float = Field(default=0.0, ge=0.0)


class LLMConfigUpdate(BaseSchema):
    label: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None
    provider: str | None = Field(default=None, max_length=64)
    model_name: str | None = Field(default=None, max_length=128)
    api_base_url: str | None = Field(default=None, max_length=512)
    api_key: SecretStr | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    cost_per_input_token: float | None = Field(default=None, ge=0.0)
    cost_per_output_token: float | None = Field(default=None, ge=0.0)


class LLMConfigResponse(BaseResponseSchema):
    label: str
    is_active: bool
    provider: str
    model_name: str
    api_base_url: str | None
    temperature: float
    max_tokens: int
    cost_per_input_token: float
    cost_per_output_token: float
