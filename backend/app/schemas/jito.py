from __future__ import annotations

import enum

from pydantic import BaseModel


class BundleStatus(str, enum.Enum):
    LANDED = "Landed"
    FAILED = "Failed"
    INVALID = "Invalid"
    PENDING = "Pending"


class BundleStatusResponse(BaseModel):
    bundle_id: str
    status: BundleStatus
    landed_slot: int | None = None
    error: str | None = None


class BundleSubmitResult(BaseModel):
    bundle_id: str


class SubmissionPath(str, enum.Enum):
    JITO = "jito"
    DIRECT_RPC = "direct_rpc"


class TransactionSubmitResult(BaseModel):
    path: SubmissionPath
    bundle_id: str | None = None
    tx_signature: str | None = None
    status: BundleStatus | None = None
