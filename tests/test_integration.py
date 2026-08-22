"""実 AWS を呼ぶ結合テスト。`-m integration` を付けたときだけ動く。"""

import pytest

from kb_app.bedrock import retrieve, retrieve_and_generate
from kb_app.config import load_settings

pytestmark = pytest.mark.integration


def test_検索でチャンクが返る():
    settings = load_settings()
    chunks = retrieve("Bedrock のナレッジベースとは何ですか", settings=settings, top_k=5)
    assert len(chunks) > 0
    assert any(c.docs_url for c in chunks), "公開 URL を復元できたチャンクが 1 件も無い"


def test_回答生成が引用付きで返る():
    settings = load_settings()
    answer = retrieve_and_generate("Bedrock のナレッジベースとは何ですか", settings=settings)
    assert answer.text
    assert answer.session_id
    assert len(answer.chunks) > 0
