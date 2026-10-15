"""Closed public Session Browser REST DTOs without transport destinations."""

from typing import Literal

from azents_runtime_control.browser_contract import (
    BrowserFrame,
    BrowserPage,
    BrowserTask,
)
from pydantic import BaseModel, ConfigDict, Field

from azents.services.runtime_browser.data import (
    RuntimeBrowserProjection,
    RuntimeBrowserReasonCode,
)


class BrowserFrameResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    url: str
    name: str

    @classmethod
    def convert_from(cls, frame: BrowserFrame) -> "BrowserFrameResponse":
        return cls(id=frame.id, url=frame.url, name=frame.name)


class BrowserPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    task_id: str
    resource_incarnation: str
    url: str
    title: str
    frames: list[BrowserFrameResponse]

    @classmethod
    def convert_from(cls, page: BrowserPage) -> "BrowserPageResponse":
        return cls(
            id=page.id,
            task_id=page.task_id,
            resource_incarnation=page.resource_incarnation,
            url=page.url,
            title=page.title,
            frames=[BrowserFrameResponse.convert_from(frame) for frame in page.frames],
        )


class BrowserTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    label: str
    resource_incarnation: str
    pages: list[BrowserPageResponse]

    @classmethod
    def convert_from(cls, task: BrowserTask) -> "BrowserTaskResponse":
        return cls(
            id=task.id,
            label=task.label,
            resource_incarnation=task.resource_incarnation,
            pages=[BrowserPageResponse.convert_from(page) for page in task.pages],
        )


class BrowserProjectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    available: bool
    reason_code: RuntimeBrowserReasonCode | None
    allow_input: bool
    tasks: list[BrowserTaskResponse]

    @classmethod
    def convert_from(
        cls, projection: RuntimeBrowserProjection
    ) -> "BrowserProjectionResponse":
        return cls(
            available=projection.available,
            reason_code=projection.reason_code,
            allow_input=projection.allow_input,
            tasks=[BrowserTaskResponse.convert_from(task) for task in projection.tasks],
        )


class BrowserClosePageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    task_id: str = Field(min_length=1, max_length=200)
    resource_incarnation: str = Field(min_length=1, max_length=200)


class BrowserAttachTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    task_id: str = Field(min_length=1, max_length=128)
    page_id: str = Field(min_length=1, max_length=128)
    resource_incarnation: str = Field(min_length=1, max_length=128)


class BrowserAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    type: Literal["attach"]
    ticket: str = Field(min_length=1, max_length=4096)
    target: BrowserAttachTarget
