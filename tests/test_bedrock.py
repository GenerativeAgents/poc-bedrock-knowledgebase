"""Bedrock Knowledge Base ラッパー。Stubber で AWS を呼ばずに検証する。"""

import boto3
import pytest
from botocore.stub import Stubber

from kb_app.bedrock import Answer, Chunk, KnowledgeBaseError, retrieve, retrieve_and_generate
from kb_app.config import Settings

SETTINGS = Settings(
    knowledge_base_id="KBID123456",
    data_source_id="DS456",
    docs_bucket="poc-kb-docs",
    region="us-east-1",
    model_arn="arn:aws:bedrock:us-east-1:1:inference-profile/us.anthropic.claude-sonnet-5",
)


@pytest.fixture
def agent_client():
    return boto3.client("bedrock-agent-runtime", region_name="us-east-1")


def test_retrieve_はチャンクと公開urlを返す(agent_client):
    response = {
        "retrievalResults": [
            {
                "content": {"text": "ナレッジベースの説明"},
                "location": {
                    "type": "S3",
                    "s3Location": {
                        "uri": "s3://poc-kb-docs/ja_jp/bedrock/latest/userguide/knowledge-base.md"
                    },
                },
                "score": 0.87,
            }
        ]
    }
    with Stubber(agent_client) as stub:
        stub.add_response("retrieve", response, {
            "knowledgeBaseId": "KBID123456",
            "retrievalQuery": {"text": "ナレッジベースとは"},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {"numberOfResults": 5}
            },
        })
        chunks = retrieve("ナレッジベースとは", settings=SETTINGS, client=agent_client)

    assert len(chunks) == 1
    assert chunks[0].text == "ナレッジベースの説明"
    assert chunks[0].score == 0.87
    assert chunks[0].docs_url == (
        "https://docs.aws.amazon.com/ja_jp/bedrock/latest/userguide/knowledge-base.html"
    )


def test_retrieve_の_top_k_が反映される(agent_client):
    with Stubber(agent_client) as stub:
        stub.add_response("retrieve", {"retrievalResults": []}, {
            "knowledgeBaseId": "KBID123456",
            "retrievalQuery": {"text": "q"},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {"numberOfResults": 12}
            },
        })
        assert retrieve("q", settings=SETTINGS, top_k=12, client=agent_client) == []


def test_対象外の_uri_なら_docs_url_は_none(agent_client):
    response = {
        "retrievalResults": [
            {
                "content": {"text": "本文"},
                "location": {"type": "S3", "s3Location": {"uri": "s3://b/other/x.txt"}},
                "score": 0.1,
            }
        ]
    }
    with Stubber(agent_client) as stub:
        stub.add_response("retrieve", response)  # パラメータ検証はこのテストの関心外
        chunks = retrieve("q", settings=SETTINGS, client=agent_client)
    assert chunks[0].docs_url is None


def test_retrieve_and_generate_は回答と引用を返す(agent_client):
    response = {
        "sessionId": "sess-1",
        "output": {"text": "ナレッジベースは RAG の仕組みです。"},
        "citations": [
            {
                "retrievedReferences": [
                    {
                        "content": {"text": "根拠テキスト"},
                        "location": {
                            "type": "S3",
                            "s3Location": {
                                "uri": "s3://poc-kb-docs/ja_jp/bedrock/latest/userguide/kb.md"
                            },
                        },
                    }
                ]
            }
        ],
    }
    with Stubber(agent_client) as stub:
        stub.add_response("retrieve_and_generate", response)  # パラメータ検証は別テストで実施
        answer = retrieve_and_generate("ナレッジベースとは", settings=SETTINGS, client=agent_client)

    assert isinstance(answer, Answer)
    assert answer.session_id == "sess-1"
    assert "RAG" in answer.text
    assert answer.chunks[0].docs_url.endswith("/kb.html")


def test_アクセス拒否はknowledgebaseerrorにする(agent_client):
    with Stubber(agent_client) as stub:
        stub.add_client_error("retrieve", service_error_code="AccessDeniedException")
        with pytest.raises(KnowledgeBaseError) as e:
            retrieve("q", settings=SETTINGS, client=agent_client)
    assert "アクセス許可" in str(e.value)


def test_有効期限切れは対処法を含む(agent_client):
    with Stubber(agent_client) as stub:
        stub.add_client_error("retrieve", service_error_code="ExpiredTokenException")
        with pytest.raises(KnowledgeBaseError) as e:
            retrieve("q", settings=SETTINGS, client=agent_client)
    assert "aws sso login" in str(e.value)


def test_sso失効は認証の案内に変換される():
    from botocore.exceptions import UnauthorizedSSOTokenError

    class 失効クライアント:
        def retrieve(self, **kwargs):
            raise UnauthorizedSSOTokenError(error_msg="token expired")

    with pytest.raises(KnowledgeBaseError) as e:
        retrieve("q", settings=SETTINGS, client=失効クライアント())
    assert "aws sso login" in str(e.value)
