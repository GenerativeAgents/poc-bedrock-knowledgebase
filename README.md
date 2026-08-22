# poc-bedrock-knowledgebase

AWS 日本語ドキュメントをコーパスにした RAG を Amazon Bedrock Knowledge Base(ストレージは S3 Vectors)で構築し、
Streamlit のローカル画面から検索パラメータを変えながら挙動を確かめるための PoC。

設計の詳細は spec を参照:
[`docs/superpowers/specs/2026-08-20-bedrock-kb-streamlit-design.md`](docs/superpowers/specs/2026-08-20-bedrock-kb-streamlit-design.md)

## アーキテクチャ

```
[ローカル] streamlit run ──┬─ bedrock-agent-runtime: Retrieve / RetrieveAndGenerate
                           └─ Claude(生成モデル)
                                    │
          Bedrock Knowledge Base ───┴─ Titan Text Embeddings V2 (1024次元)
              ├── S3 (ドキュメント)  ← data source
              └── S3 Vectors (VectorBucket + Index, cosine)
```

- `infra/knowledge-base.yaml` — CloudFormation 1スタックで一式を構築(S3 / S3 Vectors / IAM / KnowledgeBase / DataSource)
- `src/kb_app/` — `config.py`(設定解決) / `bedrock.py`(Retrieve・RetrieveAndGenerate の薄いラッパ) / `citations.py`(引用URL復元) / `app.py`(Streamlit 画面)
- `scripts/` — `fetch_aws_docs.py`(コーパス取得) / `deploy.sh` / `upload_docs.sh` / `sync.sh`

## セットアップ

対象アカウント: `288761752318`(sandbox-for-developers)/ プロファイル `ga-dev` / リージョン `us-east-1`

```bash
# 1. 依存関係のインストール
uv sync

# 2. SSO ログイン(トークン失効時も同じコマンド)
aws sso login --sso-session ga

# 3. Knowledge Base 一式をデプロイ
export AWS_PROFILE=ga-dev
./scripts/deploy.sh
# → Outputs: KnowledgeBaseId / DataSourceId / DocsBucketName / ModelArn

# 4. コーパスを S3 に投入(コーパスの用意は後述)
./scripts/upload_docs.sh

# 5. 取り込みジョブを実行(完了まで自動でポーリング)
./scripts/sync.sh

# 6. 画面を起動
uv run streamlit run src/kb_app/app.py
```

テストは以下の2種類:

```bash
uv run pytest                 # 単体テスト(AWS を呼ばない。既定)
uv run pytest -m integration  # 結合テスト(実 AWS を呼ぶ。deploy/upload/sync 済みが前提)
```

## コーパスの取得方法(`scripts/fetch_aws_docs.py`)

AWS 公式ドキュメントは各ページの `.html` を `.md` に読み替えると Markdown 版がそのまま取得できる
(HTML パース不要)。`scripts/fetch_aws_docs.py` は sitemap.xml の URL リストを受け取り、
各ガイドのページを列挙して取得する。出力パスは公開 URL の構造をそのまま写すので、
S3 キーから `docs.aws.amazon.com` の URL を機械的に復元できる(`src/kb_app/citations.py`)。

### ja_jp 全ガイドの一覧を作る(772件)

```bash
curl -s https://docs.aws.amazon.com/sitemap_index.xml \
  | grep -oE '<loc>[^<]+</loc>' | sed -E 's#</?loc>##g' \
  | grep '/ja_jp/' > /tmp/aws-docs-ja-guides-all.txt
wc -l /tmp/aws-docs-ja-guides-all.txt   # 772
```

### 1/10 サンプルを作って取得する(今回実施した規模)

```bash
# 10件に1件を抽出(約77件)
awk 'NR % 10 == 0' /tmp/aws-docs-ja-guides-all.txt > /tmp/aws-docs-ja-guides-1-10.txt

uv run scripts/fetch_aws_docs.py \
  --guides /tmp/aws-docs-ja-guides-1-10.txt \
  --outdir data/aws-docs-ja \
  --workers 4 \
  --failed-log /tmp/fetch-failed.log
```

`data/` は `.gitignore` 済み(7,000ファイル近いテキストを git に入れない)。中断しても取得済みファイルは
スキップされるので、再実行すれば続きから走る。

### 全量(772ガイド)に広げる

上で作った `/tmp/aws-docs-ja-guides-all.txt`(1/10 に絞らず全772件)を `--guides` に渡すだけでよい。
サービス上限に対して十分小さいので(下表)、スクリプトや CloudFormation テンプレートの変更は不要。
サイトマップからの実測(§2 spec)では全量で約82,000ページ相当と見積もられている。

## 実測値(2026-08-22、この PoC での実測)

| 項目 | 値 |
|---|---|
| コーパス(ディスク) | 6,810 ファイル / 約66MB(1/10 サンプル取得分。空ガイド `thingsgraph` 1件を含む) |
| S3 投入 | 6,810 objects / 54,510,043 バイト(`s3://<DocsBucket>/ja_jp/`) |
| 取り込みジョブ | `scanned=6810` `indexed=6810` `failed=0` / `COMPLETE` |
| 取り込み所要時間 | 36分23秒(`2026-08-22T02:25:49Z` 〜 `03:02:12Z`、単一ジョブをポーリング) |
| 結合テスト | `uv run pytest -m integration -v` → **2 passed**(検索でチャンク取得 / 引用付き回答生成) |
| ハイブリッド検索 | **非対応**(下記) |

### ハイブリッド検索の対応可否(実測)

`retrieve` の `retrievalConfiguration.vectorSearchConfiguration` に `overrideSearchType: HYBRID` を付けて
実際に呼び出したところ、明示的に拒否された。

```
ValidationException: HYBRID search type is not supported for search operation on index
ZRTISSGKHF. Retry your request with a different search type.
```

比較のため `overrideSearchType: SEMANTIC` は正常に受理された(5件取得)。**S3 Vectors をストレージに
使う Bedrock Knowledge Base はハイブリッド検索(BM25 + ベクトル)に対応していない**と確定した
(spec §12 の未確定事項はこれで解消。§6 の承認済み方針どおり、`app.py` に検索方式の切り替えは追加していない)。

### 生成モデルについて — なぜ `claude-sonnet-5` を既定にしなかったか

spec 作成時点では生成モデルに `us.anthropic.claude-sonnet-5` を想定していたが、実際に
`RetrieveAndGenerate` を呼ぶと次のエラーで失敗することが判明した。

```
ValidationException: Custom prompt templates must be provided for both Orchestration
and Generation when using the selected model.
```

`claude-sonnet-5` は `RetrieveAndGenerate`(KB 組み込みのオーケストレーション/生成プロンプトに依存する API)
で使うにはカスタムプロンプトテンプレートが必須で、指定しないとこのエラーになる。単純な `Converse` API の
疎通確認だけでは検出できない差異だった。実機で全候補モデルを検証した結果は次のとおり。

| 組み込みプロンプトで動作する | カスタムプロンプトが必須(不採用) |
|---|---|
| `us.anthropic.claude-sonnet-4-6` | `us.anthropic.claude-sonnet-5` |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | `us.anthropic.claude-opus-5` |
| `us.anthropic.claude-opus-4-7` | `us.anthropic.claude-opus-4-8` |
| `us.anthropic.claude-opus-4-6-v1` | `us.anthropic.claude-fable-5` |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | `us.anthropic.claude-opus-4-1-20250805-v1:0` |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | |

このため `infra/knowledge-base.yaml` の `GenerationModelId` の既定値を `us.anthropic.claude-sonnet-4-6`
(動作するモデルの中で最新の Sonnet)に変更し、`src/kb_app/app.py` の `MODELS`(サイドバーの選択肢)も
動作確認済みの6モデルのみに絞った。

## サービス上限(全量82,000ページに広げても十分な余裕がある)

| 上限 | 値 | 出典 |
|---|---|---|
| S3 Vectors: インデックスあたりベクトル数 | 20億 | S3 ユーザーガイド「制限と制約」 |
| S3 Vectors: 次元数 | 1〜4,096 | 同上 |
| S3 Vectors: 挿入レート | 2,500 ベクトル/秒/インデックス | 同上 |
| Bedrock KB: 取り込みジョブごとのファイル数 | 500万 | AWS 全般リファレンス |
| Bedrock KB: 1ファイルサイズ(テキスト) | 50 MB | 同上 |
| Bedrock KB: 取り込みジョブサイズ | 100 GB | 同上 |
| Bedrock KB: データソースあたり同時ジョブ | 1 | 同上(`sync.sh` が単一ジョブをポーリングする理由) |

S3 Vectors は Service Quotas API 非対応(`NoSuchResourceException`)のため、値はドキュメントから取得している。

## 画面での確認事項(手動)

`uv run streamlit run src/kb_app/app.py` を起動し、次を目視確認する(このリポジトリの自動化の範囲外):

1. 質問して回答が返る
2. 参照チャンクの expander が開き、`docs.aws.amazon.com` のリンクがクリックできる
3. topK を変えると参照チャンク数が変わる
4. 「検索のみ」で生成がスキップされ、スコアが見える

## 環境変数

`src/kb_app/config.py` が読む環境変数は以下のとおり。

| 環境変数 | 用途 |
|---|---|
| `STACK` | スタック名(既定 `poc-bedrock-kb`)。スクリプトとアプリの両方が参照する |
| `AWS_REGION` | リージョン(既定 `us-east-1`) |
| `KNOWLEDGE_BASE_ID` / `DATA_SOURCE_ID` / `DOCS_BUCKET` / `MODEL_ARN` | 個別に上書きしたいとき。未設定なら CloudFormation Outputs から解決する |

## 後片付け

S3 Vectors のインデックスと S3 のストレージは課金対象です。試し終えたら削除してください。

CloudFormation は**空でない S3 バケットを削除できない**ため、先にオブジェクトを空にします。

```bash
export AWS_PROFILE=ga-dev
BUCKET=$(aws cloudformation describe-stacks --stack-name poc-bedrock-kb --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='DocsBucketName'].OutputValue" --output text)
aws s3 rm "s3://$BUCKET" --recursive
aws cloudformation delete-stack --stack-name poc-bedrock-kb --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name poc-bedrock-kb --region us-east-1
```

## 関連ドキュメント

- 設計 spec: [`docs/superpowers/specs/2026-08-20-bedrock-kb-streamlit-design.md`](docs/superpowers/specs/2026-08-20-bedrock-kb-streamlit-design.md)
- 実装計画: [`docs/superpowers/plans/2026-08-20-bedrock-kb-streamlit.md`](docs/superpowers/plans/2026-08-20-bedrock-kb-streamlit.md)
