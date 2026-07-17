from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PublicSettings(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = ""
    brand_name: str = "智能客服"
    welcome_message: str = "你好，我是智能客服。请问有什么可以帮你？"
    system_prompt: str = (
        "你是一名专业、耐心的在线客服。优先依据知识库回答；"
        "知识库没有明确答案时要如实说明，不得编造政策、价格或承诺。"
    )
    temperature: float = Field(default=0.25, ge=0, le=2)
    top_k: int = Field(default=5, ge=1, le=12)
    handoff_enabled: bool = True
    low_confidence_threshold: float = Field(default=0.18, ge=0, le=10)
    max_history_messages: int = Field(default=12, ge=2, le=40)
    has_api_key: bool = False


class SettingsUpdate(BaseModel):
    base_url: str
    model: str
    brand_name: str
    welcome_message: str
    system_prompt: str
    temperature: float = Field(ge=0, le=2)
    top_k: int = Field(ge=1, le=12)
    handoff_enabled: bool = True
    low_confidence_threshold: float = Field(default=0.18, ge=0, le=10)
    max_history_messages: int = Field(default=12, ge=2, le=40)
    api_key: str | None = None
    clear_api_key: bool = False

    @field_validator("base_url", "brand_name", "welcome_message", "system_prompt")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str) -> str:
        return value.strip()


class ChatMessage(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"user", "assistant"}:
            raise ValueError("role 只能是 user 或 assistant")
        return value


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    conversation_id: str | None = Field(default=None, max_length=64)


class Source(BaseModel):
    document_id: int
    filename: str
    chunk_index: int
    excerpt: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    model: str
    usage: dict | None = None
    conversation_id: str
    trace_id: str
    route: str
    status: str
    confidence: float = 0
    handoff_id: str | None = None
    latency_ms: int = 0


class FeedbackCreate(BaseModel):
    trace_id: str = Field(min_length=8, max_length=64)
    rating: int = Field(ge=-1, le=1)
    comment: str = Field(default="", max_length=1000)


class HandoffUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"pending", "in_progress", "resolved"}:
            raise ValueError("status 必须是 pending、in_progress 或 resolved")
        return value
