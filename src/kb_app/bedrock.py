"""Bedrock Knowledge Base の薄いラッパー。

Streamlit に依存させないので、UI 抜きで単体テストできる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from kb_app.citations import docs_url
from kb_app.config import Settings

# 例外コード → 利用者向けの対処法
_HINTS = {
    "AccessDeniedException": "アクセス許可を確認してください(モデルアクセスまたは IAM)。",
    "ExpiredTokenException": "認証の有効期限が切れています。`aws sso login --sso-session ga` を実行してください。",
    "UnrecognizedClientException": "認証情報が無効です。`aws sso login --sso-session ga` を実行してください。",
    "ResourceNotFoundException": "ナレッジベースが見つかりません。`scripts/deploy.sh` を実行したか確認してください。",
    "ThrottlingException": "リクエストが多すぎます。少し待ってから再実行してください。",
    "ValidationException": "リクエストが不正です。検索パラメータを見直してください。",
}

# SSO トークン失効などクライアント側で起きる認証エラー。サービスのエラーコードを持たない。
_CREDENTIAL_HINT = "認証の有効期限が切れています。`aws sso login --sso-session ga` を実行してください。"


class KnowledgeBaseError(RuntimeError):
    """Bedrock の呼び出しが失敗した。対処法を添えて投げる。"""


@dataclass(frozen=True)
class Chunk:
    text: str
    score: float
    source_uri: str
    docs_url: str | None


@dataclass(frozen=True)
class Answer:
    text: str
    session_id: str
    chunks: list[Chunk]


def _client(settings: Settings, client: Any | None) -> Any:
    if client is not None:
        return client
    return boto3.client("bedrock-agent-runtime", region_name=settings.region)


def _raise(e: Exception) -> NoReturn:
    """例外を利用者向けの対処法付きで包み直す。必ず送出するので戻らない。"""
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        hint = _HINTS.get(code, "詳細は例外メッセージを参照してください。")
        raise KnowledgeBaseError(f"{code}: {hint}") from e
    # BotoCoreError 系(SSO 失効・資格情報なし)はサービスのエラーコードを持たない
    raise KnowledgeBaseError(f"{type(e).__name__}: {_CREDENTIAL_HINT}") from e


def _uri(reference: dict[str, Any]) -> str:
    return reference.get("location", {}).get("s3Location", {}).get("uri", "")


def _chunk(reference: dict[str, Any]) -> Chunk:
    uri = _uri(reference)
    return Chunk(
        text=reference.get("content", {}).get("text", ""),
        score=float(reference.get("score", 0.0)),
        source_uri=uri,
        docs_url=docs_url(uri) if uri else None,
    )


def retrieve(query: str, *, settings: Settings, top_k: int = 5,
             client: Any | None = None) -> list[Chunk]:
    """検索のみ。生成をスキップしてチャンクとスコアを見たいときに使う。"""
    try:
        response = _client(settings, client).retrieve(
            knowledgeBaseId=settings.knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": top_k}
            },
        )
    except (ClientError, BotoCoreError) as e:
        _raise(e)
    return [_chunk(r) for r in response.get("retrievalResults", [])]


def retrieve_and_generate(query: str, *, settings: Settings, top_k: int = 5,
                          session_id: str | None = None,
                          client: Any | None = None) -> Answer:
    """検索 + 回答生成。会話の継続は sessionId に任せる。"""
    request: dict[str, Any] = {
        "input": {"text": query},
        "retrieveAndGenerateConfiguration": {
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": settings.knowledge_base_id,
                "modelArn": settings.model_arn,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {"numberOfResults": top_k}
                },
            },
        },
    }
    if session_id:
        request["sessionId"] = session_id

    try:
        response = _client(settings, client).retrieve_and_generate(**request)
    except (ClientError, BotoCoreError) as e:
        _raise(e)

    chunks = [
        _chunk(ref)
        for citation in response.get("citations", [])
        for ref in citation.get("retrievedReferences", [])
    ]
    return Answer(
        text=response.get("output", {}).get("text", ""),
        session_id=response.get("sessionId", ""),
        chunks=chunks,
    )
