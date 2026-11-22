"""Request and response models of the HTTP API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TokenRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    user_id: int
    username: str
    display_name: str
    role: str
    branch_id: int | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int
    user: UserOut


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    strategy: Literal["full_schema", "retrieval", "retrieval_fewshot"] | None = None


class AskResponse(BaseModel):
    query_id: int | None
    status: Literal["ok", "blocked", "error", "timeout"]
    question: str
    sql: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    reason_code: str | None
    message: str | None
    relations: list[str]
    strategy: str
    repair_attempts: int
    timings_ms: dict[str, int]


class FeedbackRequest(BaseModel):
    is_correct: bool
    comment: str | None = Field(default=None, max_length=1000)


class QueryLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    query_id: int
    user_id: int
    question: str
    executed_sql: str | None
    status: str
    block_reason: str | None
    error_message: str | None
    strategy: str
    repair_attempts: int
    row_count: int | None
    total_ms: int | None
    created_at: dt.datetime


class SaleItemIn(BaseModel):
    drug_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1000)


class SaleRequest(BaseModel):
    employee_id: int = Field(gt=0)
    items: list[SaleItemIn] = Field(min_length=1, max_length=50)
    customer_id: int | None = Field(default=None, gt=0)
    prescription_id: int | None = Field(default=None, gt=0)
    branch_id: int | None = Field(default=None, gt=0)


class SaleResponse(BaseModel):
    sale_id: int
    sold_at: dt.datetime
    branch_id: int
    gross_amount: float
    discount_amount: float
    net_amount: float
    lines: list[dict[str, Any]]


class TransferRequest(BaseModel):
    to_branch_id: int = Field(gt=0)
    batch_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    employee_id: int = Field(gt=0)
    from_branch_id: int | None = Field(default=None, gt=0)


class TableResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


class SchemaObject(BaseModel):
    qualified: str
    kind: str
    ddl_summary: str


class RecommendationOut(BaseModel):
    recommendation_id: int
    table_name: str
    columns: list[str]
    index_ddl: str
    workload_size: int
    cost_before: float
    cost_after: float
    improvement_pct: float
    status: str
    created_at: dt.datetime


class ErrorResponse(BaseModel):
    code: str
    message: str
