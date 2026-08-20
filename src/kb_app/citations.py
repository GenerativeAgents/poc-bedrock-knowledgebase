"""引用元の S3 URI を docs.aws.amazon.com の公開 URL に戻す。

コーパスは取得元の URL 構造をそのまま S3 キーに写してあるので、
メタデータを別途持たなくてもリンクを復元できる。
"""

DOCS_BASE = "https://docs.aws.amazon.com/"
_PREFIX = "ja_jp/"
_SUFFIX = ".md"


def docs_url(s3_uri: str) -> str | None:
    """`s3://<bucket>/ja_jp/<path>.md` を公開ドキュメントの URL に変換する。

    対象外の URI には None を返す(呼び出し側でリンクを出さない判断に使う)。
    """
    if not s3_uri.startswith("s3://"):
        return None
    _, _, rest = s3_uri.partition("s3://")
    _, _, key = rest.partition("/")
    if not key.startswith(_PREFIX) or not key.endswith(_SUFFIX):
        return None
    return DOCS_BASE + key[: -len(_SUFFIX)] + ".html"
