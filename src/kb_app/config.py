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
