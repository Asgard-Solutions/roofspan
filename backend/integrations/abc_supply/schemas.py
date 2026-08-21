"""Pydantic schemas for the RoofSpan-facing ABC integration API (request/response DTOs).

These describe the RoofSpan Office API surface (our own endpoints), not the raw ABC contracts.
Raw ABC objects are passed through as dicts where their shape is large and documented upstream.
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


# ---- Config / connection ----
class AbcConfigUpdate(BaseModel):
    environment: Optional[str] = None  # sandbox | production
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    webhook_public_url: Optional[str] = None


class AbcSecretUpdate(BaseModel):
    client_secret: str = Field(min_length=1)


class AbcDefaultsUpdate(BaseModel):
    default_ship_to_number: Optional[str] = None
    default_branch_number: Optional[str] = None


class AbcStatusOut(BaseModel):
    environment: str
    status: str  # not_connected | connected | reconnect_required
    is_mock: bool
    has_client_id: bool
    has_client_secret: bool
    client_id_masked: Optional[str] = None
    redirect_uri: Optional[str] = None
    redirect_uri_effective: Optional[str] = None
    webhook_public_url: Optional[str] = None
    connected_identity: Optional[dict] = None
    default_ship_to_number: Optional[str] = None
    default_branch_number: Optional[str] = None
    token_scopes: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    last_connected_at: Optional[datetime] = None


class AbcConnectOut(BaseModel):
    authorize_url: str


class AbcTestResult(BaseModel):
    ok: bool
    message: str


class AbcShipToOut(BaseModel):
    number: str
    name: Optional[str] = None
    status: Optional[str] = None
    address: Optional[dict] = None
    bill_to_number: Optional[str] = None
    bill_to_name: Optional[str] = None
    sold_to_number: Optional[str] = None
    sold_to_name: Optional[str] = None
    branches: List[dict] = []
    home_branch_number: Optional[str] = None


class AbcBranchOut(BaseModel):
    number: str
    name: Optional[str] = None
    storefront: Optional[str] = None
    status: Optional[str] = None
    distance: Optional[float] = None
    address: Optional[dict] = None
    home_branch: Optional[bool] = None
