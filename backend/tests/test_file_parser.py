from app.utils.file_parser import split_text_into_chunks


def test_split_text_into_chunks_preserves_markdown_roster_lines():
    text = """
## 附录A：原总报告中的墨西哥完整内容

### 墨西哥（Mexico）

#### 球员详情

**门将**

- 1号，Raúl Rangel（GK；26岁；国家队13场/0球；俱乐部：Guadalajara）
- 13号，Guillermo Ochoa（GK；40岁；国家队152场/0球；俱乐部：AEL Limassol）
"""

    chunks = split_text_into_chunks(text, chunk_size=60, overlap=20)

    assert any(
        "- 13号，Guillermo Ochoa（GK；40岁；国家队152场/0球；俱乐部：AEL Limassol）" in chunk
        for chunk in chunks
    )


def test_split_text_into_chunks_clamps_overlap_to_make_progress():
    chunks = split_text_into_chunks("abcdefghijklmnopqrstuvwxyz", chunk_size=8, overlap=99)

    assert chunks
    assert chunks[-1].endswith("z")
