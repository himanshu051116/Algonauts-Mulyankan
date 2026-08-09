from datetime import datetime
from pydantic import BaseModel, Field

from app.domain import ProposalStatus


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    email: str
    role: str
    full_name: str | None = None
    organisation: str | None = None
    is_active: bool
    is_verified: bool
    approval_status: str | None = None
    created_at: datetime


class UserMeResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    email: str
    role: str
    is_active: bool
    is_verified: bool
    approval_status: str | None = None
    full_name: str | None = None
    organisation: str | None = None


class UserListResponse(BaseModel):
    model_config = {"from_attributes": True}
    total: int = 0
    skip: int = 0
    limit: int = 50
    users: list[UserResponse]


class UserApproveResponse(BaseModel):
    user_id: str
    status: str


class RoleAssignRequest(BaseModel):
    role: str
    reason: str = Field(min_length=3, max_length=1000)


class RoleAssignResponse(BaseModel):
    user_id: str
    role: str
    status: str


class AdministrativeOverrideRequest(BaseModel):
    status: ProposalStatus
    reason: str = Field(min_length=3, max_length=2000)
