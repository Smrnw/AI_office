"""Модели запросов. Ограничения длины защищают от случайно гигантских тел запросов."""
from typing import Literal

from pydantic import BaseModel, Field


class ProjectRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=4000)


class OfficeNameRequest(BaseModel):
    name: str = Field(max_length=200)


class NotifyTestRequest(BaseModel):
    channel: Literal["telegram", "email"]


class AutopilotRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    current_project: bool = False


class VersionRestoreRequest(BaseModel):
    folder: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)


class ProjectSelectRequest(BaseModel):
    folder: str = Field(min_length=1, max_length=120)


class LanguageRequest(BaseModel):
    language: str = Field(max_length=8)


class ChatRequest(BaseModel):
    agent_id: str = Field(max_length=64)
    message: str = Field(max_length=8000)


class ChatClearRequest(BaseModel):
    agent_id: str = Field(max_length=64)


class AgentModelSwitch(BaseModel):
    agent_id: str = Field(max_length=64)
    model_ref: str = Field(max_length=64)


class FileSaveRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str


class FileDeleteRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


class TaskUpdateRequest(BaseModel):
    task_file: str = Field(max_length=160)
    new_status: str = Field(max_length=20)
    raw_content: str = Field(max_length=500_000)


class TaskMoveRequest(BaseModel):
    task_file: str = Field(max_length=160)
    new_status: str = Field(max_length=20)
    comment: str = Field(default="", max_length=4000)


class AgentArrived(BaseModel):
    agent_id: str = Field(max_length=64)


class TaskDeleteRequest(BaseModel):
    task_file: str = Field(max_length=160)
