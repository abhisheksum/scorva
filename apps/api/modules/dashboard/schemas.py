from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class DashboardMetricCounts(BaseModel):
    total_users: int
    total_organizations: int
    total_hackathons: int
    active_hackathons: int = 0
    total_submissions: int
    evaluations_completed: int
    evaluations_running: int
    evaluations_failed: int


class DashboardAuditEventItem(BaseModel):
    id: str
    timestamp: datetime
    actor_email: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str


class DashboardOverviewResponse(BaseModel):
    counts: DashboardMetricCounts
    recent_audits: List[DashboardAuditEventItem]
    generated_at: datetime


class DashboardTrendPoint(BaseModel):
    date: str
    users: int
    organizations: int
    hackathons: int
    submissions: int
    evaluations: int


class DashboardTrendsResponse(BaseModel):
    period: str
    points: List[DashboardTrendPoint]
