from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class WorkingPaperTemplateOut(BaseModel):
    key: str
    wp_ref: str
    title: str
    statement: str
    section: str
    purpose: str
    objective: str
    tie_out: str
    procedures: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    line_codes: list[str] = Field(default_factory=list)
    account_codes: list[str] = Field(default_factory=list)
    sort_order: int = 0


class WorkingPaperTemplateListOut(BaseModel):
    templates: list[WorkingPaperTemplateOut]
    count: int


class WorkingPaperProcedureState(BaseModel):
    """Optional client-side checklist progress (not persisted server-side yet)."""

    template_key: str
    checked: list[int] = Field(default_factory=list)
    preparer: Optional[str] = None
    reviewer: Optional[str] = None
    notes: Optional[str] = None
