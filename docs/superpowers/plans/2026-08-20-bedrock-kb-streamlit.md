# Bedrock KB + Streamlit サンプル 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AWS 日本語ドキュメント 6,810ページをコーパスとした Bedrock Knowledge Base を CloudFormation で構築し、検索パラメータを調整できる Streamlit 画面から RAG の挙動を確認できるようにする。

**Architecture:** S3(ドキュメント)+ S3 Vectors(ベクトル)を Bedrock Knowledge Base が束ね、埋め込みは Titan Text Embeddings V2、生成は Claude Sonnet 5。Streamlit はローカル実行で `bedrock-agent-runtime` を直接叩く。設定値は CloudFormation Outputs から解決し、ID をコードに埋めない。

**Tech Stack:** CloudFormation (YAML) / Python 3.14 + uv / boto3 / Streamlit / pytest + botocore Stubber

**Spec:** `docs/superpowers/specs/2026-08-20-bedrock-kb-streamlit-design.md`

## Global Constraints

- リージョンは **us-east-1** 固定。プロファイルは **`ga-dev`**(アカウント 288761752318)
- スタック名は **`poc-bedrock-kb`**
- 埋め込みモデル: `amazon.titan-embed-text-v2:0` / **1024次元**
- 生成モデル: `us.anthropic.claude-sonnet-5`(推論プロファイル)
- ベクトルインデックス: `DataType=float32` / `DistanceMetric=cosine` / `Dimension=1024`
- **ベクトルインデックスの `NonFilterableMetadataKeys` に `AMAZON_BEDROCK_TEXT` と `AMAZON_BEDROCK_METADATA` を必ず指定する**(Bedrock 公式ドキュメントの要件。欠けると取り込みが失敗する)
- チャンク分割: 固定長 300トークン / オーバーラップ 20%
- コーパスは `data/aws-docs-ja/`(gitignore 済み)。**git に入れない**
- `bedrock.py` と `citations.py` と `config.py` は Streamlit に依存させない(UI 抜きでテストするため)
- 日本語でコメントを書く

---

### Task 1: 既存実装の撤去とプロジェクト初期化

別セッションが書いた実装を削除し、spec の構成で作り直す土台を作る。退避は
`/private/tmp/claude-501/-Users-shingo-github-poc-bedrock-knowledgebase/aea79fd2-7475-4b38-a145-053e1e4866f9/scratchpad/other-session-backup/` にある。

**Files:**
- Delete: `app.py`, `kb_client.py`, `citations.py`, `uv.lock`, `.env.example`, `tests/test_app.py`, `tests/test_citations.py`, `tests/test_kb_client.py`
- Restore: `README.md`(git の HEAD に戻す)
- Create: `pyproject.toml`, `src/kb_app/__init__.py`, `tests/__init__.py`

**Interfaces:**
- Consumes: なし
- Produces: `uv run pytest` が実行できる状態。パッケージ `kb_app` が `src/` レイアウトで import できる

- [ ] **Step 1: 別セッションの成果物を削除し README を復元する**

```bash
cd /Users/shingo/github/poc-bedrock-knowledgebase
rm -f app.py kb_client.py citations.py uv.lock .env.example
rm -rf tests __pycache__
git checkout README.md
git status --short
```

期待: `scripts/`、`docs/`、`.gitignore` だけが未追跡として残る。`data/` は gitignore 済みなので出てこない。

- [ ] **Step 2: pyproject.toml を作る**

```toml
[project]
name = "poc-bedrock-knowledgebase"
version = "0.1.0"
description = "AWS 日本語ドキュメントを対象にした Bedrock Knowledge Base + Streamlit サンプル"
requires-python = ">=3.11"
dependencies = [
    "boto3>=1.40",
    "streamlit>=1.40",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/kb_app"]

[tool.pytest.ini_options]
markers = [
    "integration: 実際の AWS を呼ぶテスト。既定では実行しない",
]
addopts = "-m 'not integration'"
```

- [ ] **Step 3: パッケージの空ファイルを作る**

```bash
mkdir -p src/kb_app tests
printf '"""Bedrock Knowledge Base を使う Streamlit サンプル。"""\n' > src/kb_app/__init__.py
touch tests/__init__.py
```

- [ ] **Step 4: 依存を解決して pytest が動くことを確認する**

```bash
uv sync
uv run pytest
```

期待: `no tests ran` で終了する(テストがまだ無いので正常)。エラーで落ちないこと。

- [ ] **Step 5: コミット**

```bash
git add pyproject.toml uv.lock src/kb_app/__init__.py tests/__init__.py .gitignore README.md
git commit -m "chore: spec の構成でプロジェクトを初期化"
```

---

### Task 2: citations.py — S3 URI から公開ドキュメント URL を復元する

コーパスの S3 キーは docs.aws.amazon.com の URL 構造をそのまま写しているため、
引用元のリンクをメタデータ無しで機械的に復元できる。AWS SDK に一切依存しない純粋関数なので最初に作る。

**Files:**
- Create: `src/kb_app/citations.py`
- Test: `tests/test_citations.py`

**Interfaces:**
- Consumes: なし
- Produces: `docs_url(s3_uri: str) -> str | None`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_citations.py`:

```python
"""S3 URI から公開ドキュメント URL への変換。"""

from kb_app.citations import docs_url


def test_ja_jp_の_md_キーを公開url に変換する():
    uri = "s3://poc-kb-docs/ja_jp/bedrock/latest/userguide/knowledge-base.md"
    assert docs_url(uri) == (
        "https://docs.aws.amazon.com/ja_jp/bedrock/latest/userguide/knowledge-base.html"
    )


def test_深い階層でも変換できる():
    uri = "s3://b/ja_jp/connect/latest/adminguide/delete-queue.md"
    assert docs_url(uri) == (
        "https://docs.aws.amazon.com/ja_jp/connect/latest/adminguide/delete-queue.html"
    )


def test_s3_uri_でなければ_none():
    assert docs_url("https://example.com/a.md") is None


def test_ja_jp_配下でなければ_none():
    assert docs_url("s3://b/en_us/bedrock/latest/userguide/x.md") is None


def test_md_でなければ_none():
    assert docs_url("s3://b/ja_jp/bedrock/latest/userguide/x.pdf") is None


def test_キーが空なら_none():
    assert docs_url("s3://b/") is None
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_citations.py -v
```

期待: FAIL。`ModuleNotFoundError: No module named 'kb_app.citations'`

- [ ] **Step 3: 最小の実装を書く**

`src/kb_app/citations.py`:

```python
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
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
uv run pytest tests/test_citations.py -v
```

期待: 6 passed

- [ ] **Step 5: コミット**

```bash
git add src/kb_app/citations.py tests/test_citations.py
git commit -m "feat: S3 URI から公開ドキュメント URL を復元する"
```

---

### Task 3: config.py — 設定の解決

KB ID などをコードに埋めず、環境変数 → CloudFormation Outputs の順で解決する。
設定の入口をこのファイル 1 つに閉じる。

**Files:**
- Create: `src/kb_app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `Settings` (frozen dataclass): `knowledge_base_id: str`, `data_source_id: str`, `docs_bucket: str`, `region: str`, `model_arn: str`
  - `ConfigError(RuntimeError)`
  - `load_settings(*, cfn=None, env=None) -> Settings`
  - 定数 `STACK_NAME = "poc-bedrock-kb"`, `DEFAULT_REGION = "us-east-1"`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config.py`:

```python
"""設定解決。環境変数が優先、無ければ CloudFormation Outputs。"""

import pytest

from kb_app.config import ConfigError, Settings, load_settings


class FakeCfn:
    """describe_stacks だけを持つスタブ。"""

    def __init__(self, outputs):
        self._outputs = outputs
        self.calls = 0

    def describe_stacks(self, StackName):  # noqa: N803 (boto3 の引数名に合わせる)
        self.calls += 1
        return {
            "Stacks": [
                {"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in self._outputs.items()]}
            ]
        }


OUTPUTS = {
    "KnowledgeBaseId": "KB123",
    "DataSourceId": "DS456",
    "DocsBucketName": "poc-kb-docs",
    "ModelArn": "arn:aws:bedrock:us-east-1:1:inference-profile/us.anthropic.claude-sonnet-5",
}


def test_環境変数がすべて揃っていれば_cloudformation を呼ばない():
    cfn = FakeCfn(OUTPUTS)
    env = {
        "KNOWLEDGE_BASE_ID": "envKB",
        "DATA_SOURCE_ID": "envDS",
        "DOCS_BUCKET": "envBucket",
        "MODEL_ARN": "envArn",
    }
    s = load_settings(cfn=cfn, env=env)
    assert s.knowledge_base_id == "envKB"
    assert cfn.calls == 0


def test_環境変数が無ければ_outputs から解決する():
    cfn = FakeCfn(OUTPUTS)
    s = load_settings(cfn=cfn, env={})
    assert s.knowledge_base_id == "KB123"
    assert s.data_source_id == "DS456"
    assert s.docs_bucket == "poc-kb-docs"
    assert s.model_arn.endswith("us.anthropic.claude-sonnet-5")
    assert cfn.calls == 1


def test_環境変数が一部だけなら残りを_outputs で埋める():
    cfn = FakeCfn(OUTPUTS)
    s = load_settings(cfn=cfn, env={"KNOWLEDGE_BASE_ID": "envKB"})
    assert s.knowledge_base_id == "envKB"
    assert s.docs_bucket == "poc-kb-docs"


def test_outputs にも無ければ_configerror():
    cfn = FakeCfn({"KnowledgeBaseId": "KB123"})
    with pytest.raises(ConfigError) as e:
        load_settings(cfn=cfn, env={})
    assert "DataSourceId" in str(e.value)


def test_リージョンは環境変数で上書きできる():
    cfn = FakeCfn(OUTPUTS)
    s = load_settings(cfn=cfn, env={"AWS_REGION": "ap-northeast-1"})
    assert s.region == "ap-northeast-1"


def test_settings は不変():
    s = Settings("kb", "ds", "bucket", "us-east-1", "arn")
    with pytest.raises(Exception):
        s.knowledge_base_id = "x"  # type: ignore[misc]
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_config.py -v
```

期待: FAIL。`ModuleNotFoundError: No module named 'kb_app.config'`

- [ ] **Step 3: 最小の実装を書く**

`src/kb_app/config.py`:

```python
"""設定の解決。環境変数を優先し、足りない分は CloudFormation Outputs から取る。

KB ID などをコードやコマンドに直接書かせないための入口。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import boto3

STACK_NAME = "poc-bedrock-kb"
DEFAULT_REGION = "us-east-1"

# 環境変数名 → CloudFormation の Output キー
_KEYS = {
    "knowledge_base_id": ("KNOWLEDGE_BASE_ID", "KnowledgeBaseId"),
    "data_source_id": ("DATA_SOURCE_ID", "DataSourceId"),
    "docs_bucket": ("DOCS_BUCKET", "DocsBucketName"),
    "model_arn": ("MODEL_ARN", "ModelArn"),
}


class ConfigError(RuntimeError):
    """設定が解決できない。"""


@dataclass(frozen=True)
class Settings:
    knowledge_base_id: str
    data_source_id: str
    docs_bucket: str
    region: str
    model_arn: str


def _outputs(cfn: Any, stack_name: str) -> dict[str, str]:
    stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


def load_settings(*, cfn: Any = None, env: dict[str, str] | None = None,
                  stack_name: str = STACK_NAME) -> Settings:
    """設定を解決する。CloudFormation は環境変数で埋まらなかったときだけ呼ぶ。"""
    env = os.environ if env is None else env
    region = env.get("AWS_REGION") or DEFAULT_REGION

    values = {name: env.get(env_key) for name, (env_key, _) in _KEYS.items()}
    if not all(values.values()):
        client = cfn if cfn is not None else boto3.client("cloudformation", region_name=region)
        try:
            outputs = _outputs(client, stack_name)
        except Exception as e:  # スタック未作成など
            raise ConfigError(
                f"スタック {stack_name} の Outputs を取得できません。"
                f"scripts/deploy.sh を実行したか確認してください: {e}"
            ) from e
        missing = []
        for name, (_, out_key) in _KEYS.items():
            if values[name]:
                continue
            if out_key not in outputs:
                missing.append(out_key)
            else:
                values[name] = outputs[out_key]
        if missing:
            raise ConfigError(
                f"設定を解決できません。スタック {stack_name} の Outputs に "
                f"{', '.join(missing)} がありません"
            )

    return Settings(
        knowledge_base_id=values["knowledge_base_id"],
        data_source_id=values["data_source_id"],
        docs_bucket=values["docs_bucket"],
        region=region,
        model_arn=values["model_arn"],
    )
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
uv run pytest tests/test_config.py -v
```

期待: 6 passed

- [ ] **Step 5: コミット**

```bash
git add src/kb_app/config.py tests/test_config.py
git commit -m "feat: 環境変数と CloudFormation Outputs から設定を解決する"
```

---

### Task 4: infra/knowledge-base.yaml — CloudFormation テンプレート

すべてのプロパティは 2026-08-20 に `describe-type` のスキーマと Bedrock 公式ドキュメントで確認済み。

**Files:**
- Create: `infra/knowledge-base.yaml`

**Interfaces:**
- Consumes: なし
- Produces: Outputs `KnowledgeBaseId` / `DataSourceId` / `DocsBucketName` / `ModelArn`(Task 3 の `_KEYS` と一致させること)

- [ ] **Step 1: テンプレートを書く**

`infra/knowledge-base.yaml`:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: AWS 日本語ドキュメントを対象にした Bedrock Knowledge Base (S3 Vectors)

Parameters:
  ProjectName:
    Type: String
    Default: poc-bedrock-kb
  EmbeddingModelId:
    Type: String
    Default: amazon.titan-embed-text-v2:0
  EmbeddingDimension:
    Type: Number
    Default: 1024
  GenerationModelId:
    Type: String
    Default: us.anthropic.claude-sonnet-5

Resources:
  # ---- ソースドキュメント ----
  DocsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub '${ProjectName}-docs-${AWS::AccountId}'
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256

  # ---- ベクトルストア ----
  VectorBucket:
    Type: AWS::S3Vectors::VectorBucket
    Properties:
      VectorBucketName: !Sub '${ProjectName}-vectors-${AWS::AccountId}'

  VectorIndex:
    Type: AWS::S3Vectors::Index
    Properties:
      VectorBucketName: !Ref VectorBucket
      IndexName: !Sub '${ProjectName}-index'
      DataType: float32
      Dimension: !Ref EmbeddingDimension
      DistanceMetric: cosine
      # Bedrock KB が本文とメタデータをここに格納するため、フィルタ対象から外す必要がある
      MetadataConfiguration:
        NonFilterableMetadataKeys:
          - AMAZON_BEDROCK_TEXT
          - AMAZON_BEDROCK_METADATA

  # ---- Knowledge Base 実行ロール ----
  KnowledgeBaseRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: bedrock.amazonaws.com
            Action: sts:AssumeRole
            Condition:
              StringEquals:
                aws:SourceAccount: !Ref AWS::AccountId
              ArnLike:
                AWS:SourceArn: !Sub 'arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:knowledge-base/*'
      Policies:
        - PolicyName: kb-access
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Sid: InvokeEmbeddingModel
                Effect: Allow
                Action: bedrock:InvokeModel
                Resource: !Sub 'arn:aws:bedrock:${AWS::Region}::foundation-model/${EmbeddingModelId}'
              - Sid: ReadSourceBucket
                Effect: Allow
                Action: s3:ListBucket
                Resource: !GetAtt DocsBucket.Arn
                Condition:
                  StringEquals:
                    aws:ResourceAccount: !Ref AWS::AccountId
              - Sid: ReadSourceObjects
                Effect: Allow
                Action: s3:GetObject
                Resource: !Sub '${DocsBucket.Arn}/*'
                Condition:
                  StringEquals:
                    aws:ResourceAccount: !Ref AWS::AccountId
              - Sid: S3VectorBucketReadAndWritePermission
                Effect: Allow
                Action:
                  - s3vectors:PutVectors
                  - s3vectors:GetVectors
                  - s3vectors:DeleteVectors
                  - s3vectors:QueryVectors
                  - s3vectors:GetIndex
                Resource: !GetAtt VectorIndex.IndexArn

  # ---- Knowledge Base ----
  KnowledgeBase:
    Type: AWS::Bedrock::KnowledgeBase
    Properties:
      Name: !Sub '${ProjectName}-kb'
      Description: AWS 日本語ドキュメント (ja_jp) の RAG 用ナレッジベース
      RoleArn: !GetAtt KnowledgeBaseRole.Arn
      KnowledgeBaseConfiguration:
        Type: VECTOR
        VectorKnowledgeBaseConfiguration:
          EmbeddingModelArn: !Sub 'arn:aws:bedrock:${AWS::Region}::foundation-model/${EmbeddingModelId}'
          EmbeddingModelConfiguration:
            BedrockEmbeddingModelConfiguration:
              Dimensions: !Ref EmbeddingDimension
              EmbeddingDataType: FLOAT32
      StorageConfiguration:
        Type: S3_VECTORS
        S3VectorsConfiguration:
          VectorBucketArn: !GetAtt VectorBucket.VectorBucketArn
          IndexArn: !GetAtt VectorIndex.IndexArn

  DataSource:
    Type: AWS::Bedrock::DataSource
    Properties:
      Name: !Sub '${ProjectName}-ja-docs'
      KnowledgeBaseId: !Ref KnowledgeBase
      DataSourceConfiguration:
        Type: S3
        S3Configuration:
          BucketArn: !GetAtt DocsBucket.Arn
      VectorIngestionConfiguration:
        ChunkingConfiguration:
          ChunkingStrategy: FIXED_SIZE
          FixedSizeChunkingConfiguration:
            MaxTokens: 300
            OverlapPercentage: 20

Outputs:
  KnowledgeBaseId:
    Value: !Ref KnowledgeBase
  DataSourceId:
    Value: !GetAtt DataSource.DataSourceId
  DocsBucketName:
    Value: !Ref DocsBucket
  ModelArn:
    Value: !Sub 'arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:inference-profile/${GenerationModelId}'
```

- [ ] **Step 2: テンプレートを検証する**

```bash
export AWS_PROFILE=ga-dev
aws cloudformation validate-template \
  --template-body file://infra/knowledge-base.yaml \
  --region us-east-1
```

期待: エラーなく Parameters が一覧される。

**失敗したら:** `!GetAtt VectorIndex.IndexArn` や `!GetAtt DataSource.DataSourceId` の属性名が違う可能性がある。
`aws cloudformation describe-type --type RESOURCE --type-name <型名> --region us-east-1 --query Schema --output text`
で `readOnlyProperties` を確認して直す。推測で変えないこと。

- [ ] **Step 3: コミット**

```bash
git add infra/knowledge-base.yaml
git commit -m "feat: S3 Vectors を使う Knowledge Base の CloudFormation テンプレート"
```

---

### Task 5: デプロイと投入のスクリプト

**Files:**
- Create: `scripts/deploy.sh`, `scripts/upload_docs.sh`, `scripts/sync.sh`

**Interfaces:**
- Consumes: `infra/knowledge-base.yaml` の Outputs
- Produces: なし(手続きのみ)

- [ ] **Step 1: deploy.sh を書く**

```bash
#!/usr/bin/env bash
# Knowledge Base 一式をデプロイして Outputs を表示する。
set -euo pipefail

STACK=${STACK:-poc-bedrock-kb}
REGION=${AWS_REGION:-us-east-1}
export AWS_PROFILE=${AWS_PROFILE:-ga-dev}

# 差分が無いと deploy は exit 255 で終わる。再実行のたびに落ちないよう抑止する
aws cloudformation deploy \
  --template-file "$(dirname "$0")/../infra/knowledge-base.yaml" \
  --stack-name "$STACK" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION"

echo "--- Outputs ---"
aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
```

- [ ] **Step 2: upload_docs.sh を書く**

```bash
#!/usr/bin/env bash
# コーパスを S3 に同期する。キー構造をそのまま保つので引用 URL を復元できる。
set -euo pipefail

STACK=${STACK:-poc-bedrock-kb}
REGION=${AWS_REGION:-us-east-1}
export AWS_PROFILE=${AWS_PROFILE:-ga-dev}
SRC="$(dirname "$0")/../data/aws-docs-ja"

[ -d "$SRC" ] || { echo "コーパスがありません: $SRC" >&2; exit 1; }

BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='DocsBucketName'].OutputValue" --output text)

echo "同期先: s3://$BUCKET/ja_jp/"
aws s3 sync "$SRC" "s3://$BUCKET/ja_jp/" --region "$REGION" --only-show-errors
aws s3 ls "s3://$BUCKET/ja_jp/" --recursive --summarize --region "$REGION" | tail -2
```

- [ ] **Step 3: sync.sh を書く**

```bash
#!/usr/bin/env bash
# Ingestion Job を起動し、完了までポーリングして統計を出す。
# データソースあたりの同時ジョブ上限は 1 なので、単一ジョブを待つ。
set -euo pipefail

STACK=${STACK:-poc-bedrock-kb}
REGION=${AWS_REGION:-us-east-1}
export AWS_PROFILE=${AWS_PROFILE:-ga-dev}

# Outputs の並び順は保証されないので、キーごとに個別に取る
output() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
KB=$(output KnowledgeBaseId)
DS=$(output DataSourceId)

JOB=$(aws bedrock-agent start-ingestion-job --knowledge-base-id "$KB" --data-source-id "$DS" \
  --region "$REGION" --query 'ingestionJob.ingestionJobId' --output text)
echo "取り込みジョブ開始: $JOB"

while true; do
  # API が一時的に失敗しても取り込みはサーバ側で継続している。監視だけ落とさないよう待って再試行する
  if ! OUT=$(aws bedrock-agent get-ingestion-job \
    --knowledge-base-id "$KB" --data-source-id "$DS" --ingestion-job-id "$JOB" --region "$REGION" \
    --query 'ingestionJob.[status,statistics.numberOfDocumentsScanned,statistics.numberOfNewDocumentsIndexed,statistics.numberOfDocumentsFailed]' \
    --output text 2>/dev/null); then
    sleep 20
    continue
  fi
  read -r STATUS SCANNED INDEXED FAILED <<< "$OUT"
  printf '\r%s  scanned=%s indexed=%s failed=%s   ' "$STATUS" "$SCANNED" "$INDEXED" "$FAILED"
  case "$STATUS" in
    COMPLETE) echo; echo "完了"; break ;;
    FAILED|STOPPED) echo; echo "異常終了: $STATUS" >&2; exit 1 ;;
  esac
  sleep 20
done
```

- [ ] **Step 4: 実行権限を付けて構文を確認する**

```bash
chmod +x scripts/*.sh
for f in scripts/*.sh; do bash -n "$f" && echo "OK $f"; done
```

期待: 3ファイルすべて OK。

- [ ] **Step 5: コミット**

```bash
git add scripts/deploy.sh scripts/upload_docs.sh scripts/sync.sh
git commit -m "feat: デプロイ・投入・取り込みのスクリプト"
```

---

### Task 6: bedrock.py — Retrieve と RetrieveAndGenerate

Streamlit に依存させない。テストは botocore の Stubber で AWS を呼ばずに行う。

**Files:**
- Create: `src/kb_app/bedrock.py`
- Test: `tests/test_bedrock.py`

**Interfaces:**
- Consumes: `kb_app.config.Settings`, `kb_app.citations.docs_url`
- Produces:
  - `Chunk` (frozen dataclass): `text: str`, `score: float`, `source_uri: str`, `docs_url: str | None`
  - `Answer` (frozen dataclass): `text: str`, `session_id: str`, `chunks: list[Chunk]`
  - `KnowledgeBaseError(RuntimeError)`
  - `retrieve(query: str, *, settings: Settings, top_k: int = 5, client=None) -> list[Chunk]`
  - `retrieve_and_generate(query: str, *, settings: Settings, top_k: int = 5, session_id: str | None = None, client=None) -> Answer`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_bedrock.py`:

```python
"""Bedrock Knowledge Base ラッパー。Stubber で AWS を呼ばずに検証する。"""

import boto3
import pytest
from botocore.stub import Stubber

from kb_app.bedrock import Answer, Chunk, KnowledgeBaseError, retrieve, retrieve_and_generate
from kb_app.config import Settings

SETTINGS = Settings(
    knowledge_base_id="KB123",
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
            "knowledgeBaseId": "KB123",
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
            "knowledgeBaseId": "KB123",
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


def test_アクセス拒否は_knowledgebaseerror にする(agent_client):
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
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_bedrock.py -v
```

期待: FAIL。`ModuleNotFoundError: No module named 'kb_app.bedrock'`

- [ ] **Step 3: 最小の実装を書く**

`src/kb_app/bedrock.py`:

```python
"""Bedrock Knowledge Base の薄いラッパー。

Streamlit に依存させないので、UI 抜きで単体テストできる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError

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


def _raise(e: ClientError) -> None:
    code = e.response.get("Error", {}).get("Code", "")
    hint = _HINTS.get(code, "詳細は例外メッセージを参照してください。")
    raise KnowledgeBaseError(f"{code}: {hint}") from e


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
    except ClientError as e:
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
    except ClientError as e:
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
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
uv run pytest tests/test_bedrock.py -v
```

期待: 6 passed

**失敗したら:** Stubber は API の実際のパラメータ名に厳密に一致させる。
`aws bedrock-agent-runtime retrieve help` で正しいキー名を確認して、実装ではなくテストの期待値を直すか、
両方を実 API に合わせる。パラメータ名を推測で変えないこと。

- [ ] **Step 5: コミット**

```bash
git add src/kb_app/bedrock.py tests/test_bedrock.py
git commit -m "feat: Retrieve と RetrieveAndGenerate のラッパー"
```

---

### Task 7: app.py — Streamlit 画面

**Files:**
- Create: `src/kb_app/app.py`

**Interfaces:**
- Consumes: `load_settings`, `retrieve`, `retrieve_and_generate`, `Chunk`, `Answer`, `KnowledgeBaseError`, `ConfigError`
- Produces: なし(エントリポイント)

- [ ] **Step 1: 画面を書く**

`src/kb_app/app.py`:

```python
"""Bedrock Knowledge Base を試すための Streamlit 画面。

ロジックは config / bedrock / citations に置き、ここは表示だけを持つ。
"""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from kb_app.bedrock import Answer, Chunk, KnowledgeBaseError, retrieve, retrieve_and_generate
from kb_app.config import ConfigError, load_settings

MODELS = [
    "us.anthropic.claude-sonnet-5",
    "us.anthropic.claude-opus-4-8",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
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
```

- [ ] **Step 2: import が壊れていないことを確認する**

```bash
uv run python -c "import ast,sys; ast.parse(open('src/kb_app/app.py').read()); print('構文OK')"
uv run python -c "from kb_app import bedrock, config, citations; print('import OK')"
```

期待: 両方 OK。

- [ ] **Step 3: 既存テストが壊れていないことを確認する**

```bash
uv run pytest -v
```

期待: Task 2・3・6 のテストがすべて pass。

- [ ] **Step 4: コミット**

```bash
git add src/kb_app/app.py
git commit -m "feat: Streamlit 画面"
```

---

### Task 8: 実環境での結合確認と README

ここまでは AWS を呼んでいない。実際にデプロイして通しで動かす。

**Files:**
- Create: `tests/test_integration.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: すべて
- Produces: なし

- [ ] **Step 1: デプロイする**

```bash
export AWS_PROFILE=ga-dev
./scripts/deploy.sh
```

期待: `CREATE_COMPLETE` になり、Outputs に 4 つのキーが表示される。

**失敗したら:** `aws cloudformation describe-stack-events --stack-name poc-bedrock-kb --region us-east-1 --max-items 20`
で失敗したリソースと理由を確認する。`NonFilterableMetadataKeys` が欠けていると取り込み時に失敗するので、
Task 4 のテンプレートどおりか見直す。

- [ ] **Step 2: コーパスを投入する**

```bash
./scripts/upload_docs.sh
```

期待: 6,810 オブジェクトが `s3://<bucket>/ja_jp/` に入る。

- [ ] **Step 3: 取り込みを実行する**

```bash
./scripts/sync.sh
```

期待: `COMPLETE` で終わり、`indexed` が 6,000 以上。`failed` が 0 でなければ件数を記録する。
6,810ファイル・66MB は 1ジョブの上限(500万ファイル / 100GB)に対して十分小さい。

- [ ] **Step 4: 結合テストを書いて実行する**

`tests/test_integration.py`:

```python
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
```

```bash
uv run pytest -m integration -v
```

期待: 2 passed。

- [ ] **Step 5: 画面を起動して目視確認する**

```bash
uv run streamlit run src/kb_app/app.py
```

確認すること:
1. 質問して回答が返る
2. 参照チャンクの expander が開き、`docs.aws.amazon.com` のリンクが**クリックできる**
3. topK を変えると参照チャンク数が変わる
4. 「検索のみ」で生成がスキップされ、スコアが見える
5. **ハイブリッド検索が使えるか実測する。** S3 Vectors が非対応なら
   `retrievalConfiguration` に `overrideSearchType` を足さず、サイドバーにも出さない(spec §6 で承認済み)

- [ ] **Step 6: README を書く**

セットアップ手順(uv sync → SSO ログイン → deploy → upload → sync → streamlit run)、
コーパスの取得方法(`scripts/fetch_aws_docs.py` の使い方と 1/10 の作り方)、
全量に広げる手順、実測した規模と上限を書く。spec へのリンクを含める。

- [ ] **Step 7: コミット**

```bash
git add tests/test_integration.py README.md
git commit -m "test: 結合テストと README"
```

---

## セルフレビュー結果

**spec カバレッジ:** §4 CloudFormation → Task 4 / §5 コーパス取得 → 実装済み(Task 8 の README で使い方を記載)/
§6 アプリ3ファイル → Task 2・3・6・7(`citations.py` を独立させ 4 ファイルにした。純粋関数で単体テストが最も書きやすく、
`bedrock.py` から AWS 非依存の変換ロジックを外に出せるため)/ §7 スクリプト → Task 5 / §8 エラー処理 → Task 6 の `_HINTS` /
§9 テスト → Task 2・3・6(単体)と Task 8(結合)/ §10 構成 → Task 1。

**未解決として残すもの:** ハイブリッド検索の可否は Task 8 Step 5 で実測する(spec §12、承認済み)。
