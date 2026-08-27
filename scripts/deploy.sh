#!/usr/bin/env bash
# Knowledge Base 一式をデプロイして Outputs を表示する。
set -euo pipefail

STACK=${STACK:-poc-bedrock-kb}
REGION=${AWS_REGION:-us-east-1}
export AWS_PROFILE=${AWS_PROFILE:-ga-dev}

aws cloudformation deploy \
  --template-file "$(dirname "$0")/../infra/knowledge-base.yaml" \
  --stack-name "$STACK" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION"

echo "--- Outputs ---"
aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
