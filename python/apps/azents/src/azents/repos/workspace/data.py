"""Workspace repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict


class Workspace(BaseModel):
    """Workspace domain model."""

    name: str = Field(description="Workspace name")
    handle: str = Field(description="Workspace unique handle")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "Workspace") -> Self:
        return cls.model_validate(data, from_attributes=True)


class WorkspaceCreate(BaseModel):
    """Workspace create schema."""

    name: str = Field(description="Workspace name")
    handle: str = Field(description="Workspace unique handle")


class WorkspaceUpdate(TypedDict, total=False):
    """Workspace update schema (partial update)."""

    name: str
    handle: str


class WorkspaceList(BaseModel):
    """Workspace list."""

    items: list[Workspace] = Field(description="Workspace list")


@dataclasses.dataclass(frozen=True)
class HandleConflict:
    """Duplicate handle error."""

    handle: str


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Workspace not found."""

    handle: str
