from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent import SupportAgent
from .llm import ProviderError, list_models, test_connection
from .models import ChatRequest, ChatResponse, FeedbackCreate, HandoffUpdate, SettingsUpdate
from .rag import chunk_text, extract_text
from .storage import Store


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(os.getenv("CUSTOMER_SERVICE_DATA_DIR", ROOT / "data"))


def create_app(data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="通用智能客服框架", version="2.0.0")
    app.state.store = Store(data_dir or DATA_DIR)
    app.state.agent = SupportAgent(app.state.store)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        messages = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error.get("loc", []) if part != "body")
            message = error.get("msg", "输入内容不正确")
            messages.append(f"{field}：{message}" if field else message)
        return JSONResponse(status_code=422, content={"detail": "；".join(messages)})

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/admin", include_in_schema=False)
    async def admin() -> FileResponse:
        return FileResponse(STATIC_DIR / "admin.html")

    @app.get("/api/health")
    async def health(request: Request) -> dict:
        store: Store = request.app.state.store
        settings = store.get_settings()
        return {"status": "ok", "configured": settings.has_api_key, "version": app.version}

    @app.get("/api/settings")
    async def get_settings(request: Request):
        return request.app.state.store.get_settings()

    @app.put("/api/settings")
    async def save_settings(payload: SettingsUpdate, request: Request):
        try:
            return request.app.state.store.save_settings(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/settings/test")
    async def verify_settings(request: Request) -> dict:
        store: Store = request.app.state.store
        settings = store.get_settings()
        api_key = store.get_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先保存 API Key")
        try:
            result = await test_connection(base_url=settings.base_url, api_key=api_key)
            if not settings.model:
                available_ids = [item.get("id") for item in result.get("items", []) if item.get("id")]
                preferred = (
                    "openai/gpt-4.1-mini",
                    "google/gemini-2.5-flash",
                    "openai/gpt-4o-mini",
                )
                selected = next((model_id for model_id in preferred if model_id in available_ids), None)
                if not selected and available_ids:
                    selected = available_ids[0]
                if selected:
                    values = settings.model_dump(exclude={"has_api_key"})
                    values["model"] = selected
                    store.save_settings(SettingsUpdate(**values))
                    result["selected_model"] = selected
            return result
        except (ProviderError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/models")
    async def available_models(request: Request) -> dict:
        store: Store = request.app.state.store
        settings = store.get_settings()
        api_key = store.get_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先保存 API Key")
        try:
            items = await list_models(base_url=settings.base_url, api_key=api_key)
            return {"models": items, "count": len(items)}
        except (ProviderError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/knowledge")
    async def list_knowledge(request: Request) -> dict:
        store: Store = request.app.state.store
        return {"documents": store.list_documents(), "stats": store.stats()}

    @app.post("/api/knowledge", status_code=201)
    async def upload_knowledge(request: Request, file: UploadFile = File(...)) -> dict:
        if not file.filename:
            raise HTTPException(status_code=400, detail="缺少文件名")
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="单个文件不能超过 10MB")
        try:
            text = extract_text(file.filename, content)
            chunks = chunk_text(text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not chunks:
            raise HTTPException(status_code=400, detail="文件内容太短，无法建立知识库")
        store: Store = request.app.state.store
        document_id = store.add_document(file.filename, file.content_type or "application/octet-stream", text, chunks)
        return {"id": document_id, "filename": file.filename, "chunks": len(chunks), "characters": len(text)}

    @app.delete("/api/knowledge/{document_id}")
    async def delete_knowledge(document_id: int, request: Request) -> dict:
        if not request.app.state.store.delete_document(document_id):
            raise HTTPException(status_code=404, detail="知识文件不存在")
        return {"ok": True}

    @app.get("/api/admin/metrics")
    async def agent_metrics(request: Request) -> dict:
        return request.app.state.store.metrics()

    @app.get("/api/admin/traces")
    async def agent_traces(request: Request, limit: int = 50) -> dict:
        limit = max(1, min(limit, 200))
        return {"traces": request.app.state.store.list_traces(limit)}

    @app.get("/api/admin/handoffs")
    async def handoff_queue(request: Request) -> dict:
        return {"handoffs": request.app.state.store.list_handoffs()}

    @app.patch("/api/admin/handoffs/{handoff_id}")
    async def update_handoff(handoff_id: str, payload: HandoffUpdate, request: Request) -> dict:
        if not request.app.state.store.update_handoff(handoff_id, payload.status):
            raise HTTPException(status_code=404, detail="人工转接工单不存在")
        return {"ok": True, "status": payload.status}

    @app.post("/api/feedback", status_code=201)
    async def save_feedback(payload: FeedbackCreate, request: Request) -> dict:
        try:
            request.app.state.store.add_feedback(payload.trace_id, payload.rating, payload.comment)
        except Exception as exc:
            if "FOREIGN KEY" in str(exc):
                raise HTTPException(status_code=404, detail="对应的运行记录不存在") from exc
            raise
        return {"ok": True}

    @app.get("/api/conversations/{conversation_id}")
    async def conversation_history(conversation_id: str, request: Request) -> dict:
        return {"conversation_id": conversation_id, "messages": request.app.state.store.get_messages(conversation_id, 40)}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        store: Store = request.app.state.store
        settings = store.get_settings()
        api_key = store.get_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="尚未配置 API Key，请先打开服务设置")
        if not settings.model:
            raise HTTPException(status_code=400, detail="尚未选择模型，请在管理后台点击“保存并检测连接”自动选择")
        last_user = next((message.content for message in reversed(payload.messages) if message.role == "user"), "")
        try:
            result = await request.app.state.agent.run(
                user_message=last_user,
                conversation_id=payload.conversation_id,
                settings=settings,
                api_key=api_key,
            )
        except (ProviderError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return ChatResponse(**result.__dict__)

    return app


app = create_app()
