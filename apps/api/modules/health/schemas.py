from datetime import datetime
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field


HealthStatus = Literal["healthy", "degraded", "unhealthy", "unknown"]


class ServiceCheck(BaseModel):
    status: HealthStatus
    latency_ms: Optional[float] = None
    details: Optional[str] = None


class HealthResponse(BaseModel):
    status: HealthStatus
    app_name: str = Field(default="Scorva API")
    environment: str
    version: str = Field(default="0.1.0")
    timestamp: datetime
    services: Dict[str, ServiceCheck] = Field(default_factory=dict)


class LivenessResponse(BaseModel):
    status: Literal["healthy"] = "healthy"
    timestamp: datetime
