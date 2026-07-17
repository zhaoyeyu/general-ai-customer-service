from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx"}


def extract_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("仅支持 TXT、Markdown、CSV、PDF 和 DOCX 文件")
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(content))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        document = Document(BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    else:
        text = decode_text(content)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("文件中没有可读取的文本")
    return text


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本编码无法识别，请转换为 UTF-8")


def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        parts = [paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)]
        for part in parts:
            candidate = f"{current}\n\n{part}".strip() if current else part
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                prefix = current[-overlap:] if current and overlap else ""
                current = f"{prefix}\n{part}".strip()
                if len(current) > max_chars:
                    chunks.append(current[:max_chars])
                    current = current[max_chars - overlap :]
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if len(chunk.strip()) >= 10]


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9][a-z0-9_.-]*", lowered)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
    chinese: list[str] = []
    for run in chinese_runs:
        chinese.extend(run if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)])
    return latin + chinese


@dataclass
class SearchHit:
    item: dict
    score: float


def bm25_search(query: str, items: list[dict], limit: int = 5) -> list[SearchHit]:
    if not items:
        return []
    query_terms = tokenize(query)
    if not query_terms:
        return []
    documents = [tokenize(item["content"]) for item in items]
    avg_length = sum(len(doc) for doc in documents) / max(len(documents), 1)
    document_frequency = Counter()
    for doc in documents:
        document_frequency.update(set(doc))
    scores: list[SearchHit] = []
    n_docs = len(documents)
    k1, b = 1.5, 0.75
    for item, terms in zip(items, documents):
        frequencies = Counter(terms)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * len(terms) / max(avg_length, 1))
            score += idf * frequency * (k1 + 1) / denominator
        if score > 0:
            scores.append(SearchHit(item=item, score=score))
    return sorted(scores, key=lambda hit: hit.score, reverse=True)[:limit]

