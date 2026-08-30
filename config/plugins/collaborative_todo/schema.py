from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Todo(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    content: str
    description: str | None = None
    status: TodoStatus = TodoStatus.PENDING
    owner: str = "human"
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class TodoState(BaseModel):
    todos: list[Todo] = Field(default_factory=list)
