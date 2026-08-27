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


def test_環境変数がすべて揃っていれば_cloudformation_を呼ばない():
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


def test_環境変数が無ければ_outputs_から解決する():
    cfn = FakeCfn(OUTPUTS)
    s = load_settings(cfn=cfn, env={})
    assert s.knowledge_base_id == "KB123"
    assert s.data_source_id == "DS456"
    assert s.docs_bucket == "poc-kb-docs"
    assert s.model_arn.endswith("us.anthropic.claude-sonnet-5")
    assert cfn.calls == 1


def test_環境変数が一部だけなら残りを_outputs_で埋める():
    cfn = FakeCfn(OUTPUTS)
    s = load_settings(cfn=cfn, env={"KNOWLEDGE_BASE_ID": "envKB"})
    assert s.knowledge_base_id == "envKB"
    assert s.docs_bucket == "poc-kb-docs"


def test_outputs_にも無ければ_configerror():
    cfn = FakeCfn({"KnowledgeBaseId": "KB123"})
    with pytest.raises(ConfigError) as e:
        load_settings(cfn=cfn, env={})
    assert "DataSourceId" in str(e.value)


def test_リージョンは環境変数で上書きできる():
    cfn = FakeCfn(OUTPUTS)
    s = load_settings(cfn=cfn, env={"AWS_REGION": "ap-northeast-1"})
    assert s.region == "ap-northeast-1"


def test_settings_は不変():
    s = Settings("kb", "ds", "bucket", "us-east-1", "arn")
    with pytest.raises(Exception):
        s.knowledge_base_id = "x"  # type: ignore[misc]


def test_stack_名は環境変数で上書きできる():
    class 記録するcfn(FakeCfn):
        def __init__(self, outputs):
            super().__init__(outputs)
            self.stack_names = []

        def describe_stacks(self, StackName):  # noqa: N803
            self.stack_names.append(StackName)
            return super().describe_stacks(StackName=StackName)

    cfn = 記録するcfn(OUTPUTS)
    load_settings(cfn=cfn, env={"STACK": "my-kb"})
    assert cfn.stack_names == ["my-kb"]
