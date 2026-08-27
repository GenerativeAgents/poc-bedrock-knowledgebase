# Bedrock Knowledge Base + Streamlit サンプル 設計

作成日: 2026-08-20
対象アカウント: 288761752318 (sandbox-for-developers) / プロファイル `ga-dev` / リージョン `us-east-1`

## 1. 目的とスコープ

AWS 日本語ドキュメントをコーパスとした RAG を、Bedrock Knowledge Base + S3 Vectors で構築し、
Streamlit のローカル画面から検索パラメータを変えながら挙動を確かめられるようにする。

**やること**
- CloudFormation 1スタックで KB 一式(S3 / S3 Vectors / IAM / KnowledgeBase / DataSource)を構築
- AWS 日本語ドキュメントの Markdown 版を取得して S3 に投入
- Streamlit でチャット + 引用表示 + 検索パラメータ調整

**やらないこと**
- Streamlit アプリのコンテナ化・AWS へのデプロイ(ローカル実行のみ)
- 画面からのドキュメントアップロード / 同期トリガー(スクリプトで行う)
- CI

## 2. 実測済みの前提

すべて 2026-08-20 に実環境・一次情報で確認済み。推測値ではない。

### コーパス
| 項目 | 値 | 確認方法 |
|---|---|---|
| ja_jp ガイド総数 | 772 | `sitemap_index.xml` を `/ja_jp/` で絞り込み |
| 全量の推定ページ数 | 約82,000(平均106 / 中央値23) | 25ガイドの無作為サンプリング |
| **今回取得(1/10)** | **78ガイド / 6,664ページ**(サイトマップ上 6,665 の 99.98%) | 実取得(完了) |
| ディスク上の総量 | 6,810ファイル / 66MB / 3,216万文字 | 上記に動作確認で取得した `amazon-mq`(146ページ)を含む |
| 空のガイド | 1(`thingsgraph`) | 提供終了サービスでサイトマップが空。取得漏れではない |
| 取得形式 | Markdown | `<page>.html` → `<page>.md` が 200 を返す |
| robots.txt | 現行ドキュメントは許可 | 禁止は 2008〜2015 の旧APIバージョンのみ |

`.md` 版が直接取れるため HTML パースは不要。同一ページで HTML 抽出 3,139文字 に対し `.md` は 7,278バイト
で、見出し・アンカー・相対リンクが保持される。

### サービス上限(全量82,000ページに広げても余裕がある)
| 上限 | 値 | 出典 |
|---|---|---|
| S3 Vectors: インデックスあたりベクトル数 | **20億** | S3 ユーザーガイド「制限と制約」 |
| S3 Vectors: 次元数 | 1〜4,096 | 同上 |
| S3 Vectors: 挿入レート | 2,500 ベクトル/秒/インデックス | 同上 |
| Bedrock KB: 取り込みジョブごとのファイル数 | 500万 | AWS 全般リファレンス |
| Bedrock KB: 1ファイルサイズ(テキスト) | 50 MB | 同上 |
| Bedrock KB: 取り込みジョブサイズ | 100 GB | 同上 |
| Bedrock KB: データソースあたり同時ジョブ | 1 | 同上 |

S3 Vectors は Service Quotas API 非対応(`NoSuchResourceException`)のため、値はドキュメントから取得した。

### モデル
- 埋め込み: `amazon.titan-embed-text-v2:0` / 1024次元(`invoke-model` で確認済み)
- 生成: **`us.anthropic.claude-sonnet-4-6`**(推論プロファイル)

> **2026-08-22 修正。** 当初この欄は `us.anthropic.claude-sonnet-5` としていたが誤りだった。
> 確認に使ったのは `converse` API であり、実際に使う `RetrieveAndGenerate` は要件が異なる。
> `claude-sonnet-5` は `RetrieveAndGenerate` でカスタムプロンプトテンプレートが必須で、
> 指定すると `ValidationException` になる。全推論プロファイルを実測した結果は §12 を参照。

## 3. アーキテクチャ

```
[ローカル] streamlit run ──┬─ bedrock-agent-runtime: Retrieve / RetrieveAndGenerate
                           └─ Claude Sonnet 5
                                    │
          Bedrock Knowledge Base ───┴─ Titan Text Embeddings V2 (1024次元)
              ├── S3 (ドキュメント)  ← data source
              └── S3 Vectors (VectorBucket + Index, cosine)
```

## 4. CloudFormation (`infra/knowledge-base.yaml`)

| 論理ID | 型 | 備考 |
|---|---|---|
| `DocsBucket` | `AWS::S3::Bucket` | ソース Markdown |
| `VectorBucket` | `AWS::S3Vectors::VectorBucket` | |
| `VectorIndex` | `AWS::S3Vectors::Index` | `DataType=float32` / `Dimension=1024` / `DistanceMetric=cosine`(3つとも必須) |
| `KnowledgeBaseRole` | `AWS::IAM::Role` | DocsBucket 読取 + s3vectors 操作 + Titan 呼び出しのみ |
| `KnowledgeBase` | `AWS::Bedrock::KnowledgeBase` | `StorageConfiguration.Type=S3_VECTORS` |
| `DataSource` | `AWS::Bedrock::DataSource` | DocsBucket 参照 / 固定長チャンク(300トークン・オーバーラップ20%) |

Outputs: `KnowledgeBaseId` / `DataSourceId` / `DocsBucketName`。アプリはここから設定を得る。ID のハードコード禁止。

## 5. コーパス取得 (`scripts/fetch_aws_docs.py`)

実装済み・動作確認済み。

- 入力: sitemap.xml の URL リスト / 出力ディレクトリ / 同時接続数
- 各ガイドの sitemap から `.html` を列挙し `.md` に読み替えて取得
- 出力パスは公開 URL の構造をそのまま写す
  - `data/aws-docs-ja/bedrock/latest/userguide/knowledge-base.md`
  - ↔ `https://docs.aws.amazon.com/ja_jp/bedrock/latest/userguide/knowledge-base.html`
  - **S3 キーから出典 URL を機械的に復元できるので、引用リンク用のメタデータファイルが不要**
- 取得済みはスキップ(中断しても続きから走る。再実行が全件スキップになることを確認済み)
- 403/429/5xx は指数バックオフ、404 はスキップして失敗ログへ
- サイトマップにまれに混ざる `.html.html` の二重エントリを正規化する
- 同時接続は既定4。CloudFront に絞られるため上げすぎない

コーパスは `data/` に置き `.gitignore` 済み。**7,000ファイルを git に入れない。**

## 6. Streamlit アプリ (`src/kb_app/`)

3ファイルに分離する。

- `config.py` — 環境変数、無ければ `describe-stacks` の Outputs から解決。設定の入口を1か所に閉じる
- `bedrock.py` — `retrieve()` / `retrieve_and_generate()` の薄いラッパ。**Streamlit に依存させない**(単体テスト可能にするため)
- `app.py` — 画面のみ。ロジックを持たせない

画面:
- メイン: チャット。回答の下に expander で参照チャンク + スコア + 出典リンク(S3 キーから復元した docs.aws.amazon.com の URL)
- サイドバー: topK / 生成モデル / 検索方式 / 「検索のみ(生成をスキップ)」トグル
- 会話継続は `RetrieveAndGenerate` の `sessionId` に委譲。履歴を自前で組み立てない

**検索方式について**: S3 Vectors がハイブリッド検索に対応しているかは未検証。実装時に実測し、
非対応ならサイドバーから当該コントロールを削除して topK とモデル切り替えのみとする(承認済み)。

## 7. 運用スクリプト

| スクリプト | 役割 |
|---|---|
| `scripts/fetch_aws_docs.py` | コーパス取得(実装済み) |
| `scripts/deploy.sh` | `aws cloudformation deploy` |
| `scripts/upload_docs.sh` | `aws s3 sync data/aws-docs-ja s3://<DocsBucket>/ja_jp/` |
| `scripts/sync.sh` | Ingestion Job 起動 → 完了までポーリング → scanned/indexed/failed を表示 |

同時ジョブ上限が1なので `sync.sh` は単一ジョブを長時間ポーリングする。

## 8. エラー処理

| 事象 | 画面の表示 |
|---|---|
| SSO トークン失効 | `aws sso login --sso-session ga` を実行してください |
| KB が空 | `scripts/sync.sh` を実行してください |
| `AccessDeniedException` | 該当モデルのアクセス許可を確認してください |
| `ThrottlingException` | botocore の adaptive retry に委譲。失敗時は再試行を促す |

例外は握りつぶさず、対処法を添えて表示する。

## 9. テスト

- `bedrock.py` の単体テスト: botocore `Stubber` を使い AWS を叩かない
- 結合テスト: 実 AWS を叩くため `-m integration` でオプトイン。既定では実行しない

## 10. リポジトリ構成

```
├── pyproject.toml              # uv
├── infra/knowledge-base.yaml
├── data/                       # .gitignore 済み
├── src/kb_app/{config,bedrock,app}.py
├── scripts/{fetch_aws_docs.py,deploy.sh,upload_docs.sh,sync.sh}
└── tests/
```

## 11. 段階

1. **今回(1/10)** — 6,810ページで構築し、チャンク品質・引用・レイテンシを確認
2. **全量(任意)** — 同じスクリプトで残り694ガイドを取得。上限は §2 のとおり全量でも余裕がある。
   追加コストは埋め込みが概算数ドル、加えて取得と取り込みの時間

## 12. 未確定事項とその決着

いずれも Task 8 の実環境検証(2026-08-22)で決着した。

### S3 Vectors のハイブリッド検索 → **非対応**(決着)

`retrieve` の `vectorSearchConfiguration.overrideSearchType` に `HYBRID` を指定すると次で拒否される。

```
ValidationException: HYBRID search type is not supported for search operation on index ZRTISSGKHF
```

`SEMANTIC` は受理される。設計時の合意どおり、画面の検索方式切り替えは実装しない。

### 生成モデルの選定 → **既定を `claude-sonnet-4-6` に変更**(決着)

全 `us.anthropic.*` 推論プロファイルで `RetrieveAndGenerate` を実測した結果:

| 組み込みプロンプトで動作 | カスタムプロンプト必須 |
|---|---|
| `claude-sonnet-4-6` / `claude-sonnet-4-5-20250929-v1:0` | `claude-sonnet-5` / `claude-opus-5` |
| `claude-opus-4-7` / `claude-opus-4-6-v1` / `claude-opus-4-5-20251101-v1:0` | `claude-opus-4-8` / `claude-fable-5` |
| `claude-haiku-4-5-20251001-v1:0` | `claude-opus-4-1-20250805-v1:0` |

最新世代(5系・opus-4-8・fable-5)は Bedrock KB 側の組み込みプロンプトテンプレートが未提供。
`claude-3-sonnet` / `claude-3-haiku` / `claude-sonnet-4-20250514` はこのアカウントでモデルアクセスなし(404)。

### 取り込み所要時間 → **6,810ページで36分23秒**(実測)

`2026-08-22T02:25:49Z` 〜 `03:02:12Z`。scanned=6810 / indexed=6810 / failed=0。
全量(約82,000ページ)へ単純に外挿すると約7時間強だが、1ジョブあたりの上限
(ファイル数500万 / 100GB)には十分収まる。
