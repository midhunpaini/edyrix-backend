from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CommonResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "OK"
    data: T | None = None

    @classmethod
    def ok(cls, data: T, message: str = "OK") -> "CommonResponse[T]":
        return cls(success=True, message=message, data=data)

    @classmethod
    def error(cls, message: str) -> "CommonResponse[None]":
        return cls(success=False, message=message, data=None)


class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "OK"
    data: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool


class MessageResponse(BaseModel):
    message: str
