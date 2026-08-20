# Task 3 報告: config.py — 設定の解決

## 実装したこと

`src/kb_app/config.py` と `tests/test_config.py` を新規作成しました。

### `config.py` 概要

環境変数と CloudFormation Outputs から設定を解決するモジュール。優先順位は環境変数 > CloudFormation Outputs。

**公開 API:**
- `Settings` (frozen dataclass): knowledge_base_id, data_source_id, docs_bucket, region, model_arn
- `ConfigError(RuntimeError)`: 設定解決失敗時の例外
- `load_settings(*, cfn=None, env=None, stack_name=STACK_NAME) -> Settings`: 設定ローダー
- 定数: `STACK_NAME = "poc-bedrock-kb"`, `DEFAULT_REGION = "us-east-1"`

**内部実装:**
- `_KEYS`: 環境変数名と CloudFormation Output キーの対応表
- `_outputs()`: CloudFormation Outputs 抽出ヘルパー

**動作**:
1. 環境変数に値があればそれを使う
2. 足りない値は CloudFormation Outputs から取得
3. 全て環境変数で揃っていれば CloudFormation は呼ばない
4. 不足値がある場合、AWS_REGION で region を上書き可能
5. 必須フィールドが CloudFormation にも無ければ ConfigError を発生

### テスト設計

6 つのテストで以下を検証:

| テスト | 目的 |
|---|---|
| `test_環境変数がすべて揃っていれば_cloudformation_を呼ばない` | CloudFormation 呼び出しの最小化 |
| `test_環境変数が無ければ_outputs_から解決する` | CloudFormation Outputs での解決 |
| `test_環境変数が一部だけなら残りを_outputs_で埋める` | ハイブリッド解決 |
| `test_outputs_にも無ければ_configerror` | エラーハンドリング |
| `test_リージョンは環境変数で上書きできる` | region の上書き |
| `test_settings_は不変` | frozen dataclass の不変性 |

## TDD Evidence

### RED: 失敗の確認

**実装後に config.py を退避して再取得した RED 出力です。事後的な再現であることを明記します。**

```bash
$ uv run pytest tests/test_config.py -v
```

**出力:**
```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0 -- /Users/shingo/github/poc-bedrock-knowledgebase/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/shingo/github/poc-bedrock-knowledgebase
configfile: pyproject.toml
plugins: anyio-4.14.2
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_config.py _____________________
ImportError while importing test module '/Users/shingo/github/poc-bedrock-knowledgebase/tests/test_config.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../.local/share/uv/python/cpython-3.12.12-macos-aarch64-none/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_config.py:5: in <module>
    from kb_app.config import ConfigError, Settings, load_settings
E   ModuleNotFoundError: No module named 'kb_app.config'
=========================== short test summary info ============================
ERROR tests/test_config.py
============================== Interrupted: 1 error during collection ============================
=============================== 1 error in 0.04s =======================================
```

**期待通り:** モジュール未作成のため collection error

### GREEN: 成功の確認

```bash
$ uv run pytest tests/test_config.py -v
```

**出力:**
```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0 -- /Users/shingo/github/poc-bedrock-knowledgebase/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/shingo/github/poc-bedrock-knowledgebase
configfile: pyproject.toml
plugins: anyio-4.14.2
collecting ... collected 6 items

tests/test_config.py::test_環境変数がすべて揃っていれば_cloudformation_を呼ばない PASSED [ 16%]
tests/test_config.py::test_環境変数が無ければ_outputs_から解決する PASSED [ 33%]
tests/test_config.py::test_環境変数が一部だけなら残りを_outputs_で埋める PASSED [ 50%]
tests/test_config.py::test_outputs_にも無ければ_configerror PASSED       [ 66%]
tests/test_config.py::test_リージョンは環境変数で上書きできる PASSED     [ 83%]
tests/test_config.py::test_settings_は不変 PASSED                        [100%]

============================== 6 passed in 0.06s =======================================
```

**成功:** 6/6 PASSED

## 変更したファイル

1. **`src/kb_app/config.py`** (80 行): 新規作成
   - Settings クラス
   - ConfigError 例外クラス
   - load_settings 関数
   - ヘルパー関数とキー定義

2. **`tests/test_config.py`** (78 行): 新規作成
   - FakeCfn スタブクラス
   - 6 つのテスト関数

## セルフレビュー

**実装の正確性:**
- ✅ Settings は frozen dataclass で、ブリーフの 5 フィールドを正確に実装
- ✅ CloudFormation Output 名が後続 Task 4 の Outputs と一対一対応（綴りを変えていない）
- ✅ 環境変数優先の優先順位が正しい
- ✅ 環境変数で全て埋まった場合、CloudFormation を呼ばない（早期リターン）
- ✅ cfn パラメータでテスタビリティを確保

**テストの妥当性:**
- ✅ 各テストは実際の振る舞いを検証（モック振る舞いではなく）
- ✅ CloudFormation 呼び出し回数を `FakeCfn.calls` でアサート
- ✅ テスト関数名がブリーフの記法を正規化（スペース除去）
- ✅ テスト出力にノイズなし

**その他チェック:**
- ✅ citations.py（Task 2）など他のファイルを触っていない
- ✅ 環境変数テストで `env={}` を明示的に渡している
- ✅ region はデフォルト値を持ち、AWS_REGION で上書き可能
- ✅ エラーメッセージは日本語で分かりやすい

## 懸念

なし。TDD 要件（テスト → 失敗 → 実装 → 成功）を満たし、全テストが成功しています。

## コミット

```
a2cca75 feat: 環境変数と CloudFormation Outputs から設定を解決する
```

---

**作成日:** 2026-08-20  
**テスト結果:** 6/6 PASSED
