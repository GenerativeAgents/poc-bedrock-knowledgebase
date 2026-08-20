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
