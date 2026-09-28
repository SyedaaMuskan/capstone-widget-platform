"""Pydantic models = validation at the boundary."""
from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
RESERVED_FIELD_NAMES = {"hp"}

WidgetType = Literal["signup_form", "contact_form", "cta_popover"]
FieldType = Literal["text", "email", "textarea", "tel"]


class FieldDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    label: str = Field(min_length=1, max_length=100)
    type: FieldType = "text"
    required: bool = False
    max_length: int = Field(500, ge=1, le=5000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME_RE.match(v) or v in RESERVED_FIELD_NAMES:
            raise ValueError("name must match ^[a-z][a-z0-9_]{0,31}$ and not be reserved")
        return v


class WidgetOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme_color: str = Field("#2563eb", pattern=r"^#[0-9a-fA-F]{6}$")
    success_message: str = Field("Thanks! We'll be in touch.", max_length=200)
    position: Literal["inline", "bottom-right", "bottom-left", "center"] = "inline"
    delay_seconds: int = Field(0, ge=0, le=300)


def _unique_names(fields: Optional[list[FieldDef]]) -> None:
    if fields is not None:
        names = [f.name for f in fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique")


class WidgetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: WidgetType
    title: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    button_text: str = Field("Submit", min_length=1, max_length=40)
    fields: list[FieldDef] = Field(min_length=1, max_length=12)
    options: WidgetOptions = Field(default_factory=WidgetOptions)

    @model_validator(mode="after")
    def _check(self):
        _unique_names(self.fields)
        return self


class WidgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Optional[WidgetType] = None
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    button_text: Optional[str] = Field(None, min_length=1, max_length=40)
    fields: Optional[list[FieldDef]] = Field(None, min_length=1, max_length=12)
    options: Optional[WidgetOptions] = None

    @model_validator(mode="after")
    def _check(self):
        _unique_names(self.fields)
        return self


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class SubmissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    widget_id: str = Field(pattern=r"^[A-Za-z0-9_-]{4,32}$")
    data: dict[str, Any]
    hp: Any = ""  # honeypot: humans never fill it
    idempotency_key: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]{8,100}$")
