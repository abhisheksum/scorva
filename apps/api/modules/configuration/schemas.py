from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
import uuid
from pydantic import BaseModel, Field, field_validator


class ConfigurationSettingResponse(BaseModel):
    key: str
    tier: str
    data_type: str
    default_value: str
    current_value: str
    allow_org_override: bool
    allow_hackathon_override: bool
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    is_configurable: bool
    version: int
    effect_timing: str = "immediate"
    description: Optional[str] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfigurationSettingUpdate(BaseModel):
    value: str = Field(..., description="Serialized string representation of the new setting value")
    expected_version: int = Field(..., description="Optimistic concurrency control: current version of the setting")
    change_reason: Optional[str] = Field(None, max_length=500, description="Audit reason for the configuration change")


class ConfigurationRollbackRequest(BaseModel):
    target_version: int = Field(..., description="Historical version number to restore")
    expected_version: int = Field(..., description="Optimistic concurrency control: current version of the setting")
    change_reason: Optional[str] = Field(None, max_length=500, description="Audit rationale for the rollback")


class ConfigurationOverrideCreate(BaseModel):
    scope_type: Literal["organization", "hackathon"]
    scope_id: uuid.UUID
    value: str = Field(..., description="Serialized string representation of the override value")
    expected_version: Optional[int] = Field(None, description="Expected version of existing override (if updating)")
    change_reason: Optional[str] = Field(None, max_length=500)


class ConfigurationOverrideResponse(BaseModel):
    id: uuid.UUID
    setting_key: str
    scope_type: str
    scope_id: uuid.UUID
    override_value: str
    version: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfigurationHistoryResponse(BaseModel):
    id: uuid.UUID
    setting_key: str
    scope_type: str
    scope_id: uuid.UUID
    old_value: Optional[str]
    new_value: str
    change_type: str
    restored_from_version: Optional[int]
    version: int
    actor_user_id: Optional[uuid.UUID]
    client_ip: Optional[str]
    change_reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class EffectiveConfiguration(BaseModel):
    """
    Resolved typed configuration object for a specific scope context.
    """
    judge_require_override_rationale: bool = True
    judge_min_override_rationale_length: int = 20
    judge_allow_score_adjustment_after_finalization: bool = False

    extract_max_compressed_bytes: int = 52428800
    extract_max_uncompressed_bytes: int = 262144000
    extract_max_file_count: int = 1000
    extract_max_archive_depth: int = 5
    extract_allow_symlinks: bool = False

    ai_default_provider: str = "ollama"
    ai_default_model: str = "llama3.3:70b"
    ai_max_tokens: int = 4096
    ai_temperature: float = 0.0
    ai_evaluation_timeout_seconds: int = 300

    eval_max_retries: int = 3
    eval_lock_timeout_seconds: int = 300

    auth_mfa_enforced: bool = False

    authz_cache_ttl_seconds: int = 30
    authz_policy_version_check_seconds: int = 5

    raw_values: Dict[str, str] = Field(default_factory=dict)
