"""Bedrock Knowledge Base を試すための Streamlit 画面。

ロジックは config / bedrock / citations に置き、ここは表示だけを持つ。
"""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from kb_app.bedrock import Answer, Chunk, KnowledgeBaseError, retrieve, retrieve_and_generate
from kb_app.config import ConfigError, load_settings

# RetrieveAndGenerate が組み込みプロンプトで動作するモデルのみ。
# claude-sonnet-5 / opus-5 / opus-4-8 / fable-5 はカスタムプロンプトテンプレートが必須で、
# 指定すると ValidationException になるため載せない(2026-08-22 実測)。
MODELS = [
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-opus-4-7",
    "us.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]

st.set_page_config(page_title="AWS ドキュメント RAG", page_icon="📚", layout="wide")
st.title("📚 AWS 日本語ドキュメント RAG")


@st.cache_resource
def _settings():
    return load_settings()


try:
    settings = _settings()
except ConfigError as e:
    st.error(str(e))
    st.stop()

with st.sidebar:
    st.subheader("検索設定")
    top_k = st.slider("取得チャンク数 (topK)", min_value=1, max_value=20, value=5)
    model_id = st.selectbox("生成モデル", MODELS, index=0)
    search_only = st.toggle("検索のみ(生成をスキップ)", value=False,
                            help="回答を作らず、検索結果とスコアだけを見る")
    st.divider()
    st.caption(f"KB: `{settings.knowledge_base_id}`")
    st.caption(f"リージョン: `{settings.region}`")
    if st.button("会話をリセット"):
        st.session_state.pop("session_id", None)
        st.session_state.pop("messages", None)
        st.rerun()

# 選んだモデルを ARN に反映する(frozen dataclass なので replace で作り直す)
settings = replace(
    settings, model_arn=settings.model_arn.rsplit("/", 1)[0] + "/" + model_id
)

st.session_state.setdefault("messages", [])


def _render_chunks(chunks: list[Chunk], label: str) -> None:
    if not chunks:
        st.caption("参照チャンクなし")
        return
    with st.expander(f"{label}({len(chunks)}件)"):
        for i, c in enumerate(chunks, 1):
            st.markdown(f"**{i}. スコア {c.score:.4f}**")
            if c.docs_url:
                st.markdown(f"[{c.docs_url}]({c.docs_url})")
            else:
                st.caption(c.source_uri or "出典不明")
            st.text(c.text[:800])
            st.divider()


for m in st.session_state["messages"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("chunks"):
            _render_chunks(m["chunks"], "参照チャンク")

if prompt := st.chat_input("AWS ドキュメントについて質問してください"):
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            if search_only:
                with st.spinner("検索中..."):
                    chunks = retrieve(prompt, settings=settings, top_k=top_k)
                body = f"検索のみ実行しました({len(chunks)}件)。"
                st.markdown(body)
                _render_chunks(chunks, "検索結果")
            else:
                with st.spinner("検索と生成中..."):
                    answer: Answer = retrieve_and_generate(
                        prompt,
                        settings=settings,
                        top_k=top_k,
                        session_id=st.session_state.get("session_id"),
                    )
                st.session_state["session_id"] = answer.session_id
                body, chunks = answer.text, answer.chunks
                st.markdown(body)
                _render_chunks(chunks, "参照チャンク")
        except KnowledgeBaseError as e:
            st.error(str(e))
            body, chunks = f"エラー: {e}", []

    st.session_state["messages"].append(
        {"role": "assistant", "content": body, "chunks": chunks}
    )
