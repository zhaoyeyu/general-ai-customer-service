from __future__ import annotations

from urllib.parse import urlparse

import httpx


class ProviderError(RuntimeError):
    pass


def endpoint(base_url: str, path: str) -> str:
    cleaned = base_url.rstrip("/")
    return f"{cleaned}/{path.lstrip('/')}"


def validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API 地址必须是有效的 HTTP(S) URL")


async def chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str | None,
    messages: list[dict],
    temperature: float,
) -> dict:
    validate_base_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "General AI Customer Service",
    }
    payload = {
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if model:
        payload["model"] = model
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(endpoint(base_url, "chat/completions"), headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise ProviderError(f"无法连接模型服务：{exc}") from exc
    if response.is_error:
        try:
            detail = response.json().get("error", {}).get("message") or response.text
        except ValueError:
            detail = response.text
        raise ProviderError(f"模型服务返回 {response.status_code}：{detail[:300]}")
    data = response.json()
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("模型服务响应格式不正确") from exc
    return {"answer": answer, "model": data.get("model") or model or "provider-default", "usage": data.get("usage")}


async def list_models(*, base_url: str, api_key: str) -> list[dict]:
    validate_base_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(endpoint(base_url, "models"), headers=headers)
    except httpx.RequestError as exc:
        raise ProviderError(f"连接失败：{exc}") from exc
    if response.is_error:
        raise ProviderError(f"验证失败，服务返回 HTTP {response.status_code}")
    data = response.json()
    models = []
    for item in data.get("data", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        pricing = item.get("pricing") or {}
        models.append(
            {
                "id": item["id"],
                "name": item.get("name") or item["id"],
                "context_length": item.get("context_length"),
                "prompt_price": pricing.get("prompt"),
                "completion_price": pricing.get("completion"),
            }
        )
    return models[:1000]


async def test_connection(*, base_url: str, api_key: str) -> dict:
    validate_base_url(base_url)
    parsed = urlparse(base_url)
    key_info = None
    if parsed.hostname and parsed.hostname.lower().endswith("openrouter.ai"):
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(endpoint(base_url, "key"), headers=headers)
        except httpx.RequestError as exc:
            raise ProviderError(f"连接失败：{exc}") from exc
        if response.is_error:
            raise ProviderError(f"API Key 验证失败，OpenRouter 返回 HTTP {response.status_code}")
        raw = response.json().get("data") or {}
        key_info = {
            "usage": raw.get("usage"),
            "limit": raw.get("limit"),
            "limit_remaining": raw.get("limit_remaining"),
            "is_free_tier": raw.get("is_free_tier"),
        }
    models = await list_models(base_url=base_url, api_key=api_key)
    return {"ok": True, "models": len(models), "items": models, "key_info": key_info}
