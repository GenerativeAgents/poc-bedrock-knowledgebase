"""S3 URI から公開ドキュメント URL への変換。"""

from kb_app.citations import docs_url


def test_ja_jp_の_md_キーを公開urlに変換する():
    uri = "s3://poc-kb-docs/ja_jp/bedrock/latest/userguide/knowledge-base.md"
    assert docs_url(uri) == (
        "https://docs.aws.amazon.com/ja_jp/bedrock/latest/userguide/knowledge-base.html"
    )


def test_深い階層でも変換できる():
    uri = "s3://b/ja_jp/connect/latest/adminguide/delete-queue.md"
    assert docs_url(uri) == (
        "https://docs.aws.amazon.com/ja_jp/connect/latest/adminguide/delete-queue.html"
    )


def test_s3_uriでなければ_none():
    assert docs_url("https://example.com/a.md") is None


def test_ja_jp_配下でなければ_none():
    assert docs_url("s3://b/en_us/bedrock/latest/userguide/x.md") is None


def test_mdでなければ_none():
    assert docs_url("s3://b/ja_jp/bedrock/latest/userguide/x.pdf") is None


def test_キーが空なら_none():
    assert docs_url("s3://b/") is None
