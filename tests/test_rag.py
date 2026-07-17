from app.rag import bm25_search, chunk_text, extract_text


def test_extract_and_chunk_text():
    text = extract_text("faq.md", "退换货政策\n\n商品签收后七天内可以申请退货。".encode("utf-8"))
    chunks = chunk_text(text, max_chars=30, overlap=5)
    assert chunks
    assert "退换货政策" in chunks[0]


def test_bm25_handles_chinese_query():
    items = [
        {"content": "商品签收后七天内可以申请无理由退货", "filename": "售后.md"},
        {"content": "会员积分可以兑换优惠券", "filename": "会员.md"},
    ]
    hits = bm25_search("退货需要几天内申请", items, limit=1)
    assert hits
    assert hits[0].item["filename"] == "售后.md"


def test_rejects_unsupported_file():
    try:
        extract_text("archive.zip", b"test")
    except ValueError as exc:
        assert "仅支持" in str(exc)
    else:
        raise AssertionError("unsupported file should fail")

