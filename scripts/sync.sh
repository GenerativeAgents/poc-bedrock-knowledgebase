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
  read -r STATUS SCANNED INDEXED FAILED < <(aws bedrock-agent get-ingestion-job \
    --knowledge-base-id "$KB" --data-source-id "$DS" --ingestion-job-id "$JOB" --region "$REGION" \
    --query 'ingestionJob.[status,statistics.numberOfDocumentsScanned,statistics.numberOfNewDocumentsIndexed,statistics.numberOfDocumentsFailed]' \
    --output text)
  printf '\r%s  scanned=%s indexed=%s failed=%s   ' "$STATUS" "$SCANNED" "$INDEXED" "$FAILED"
  case "$STATUS" in
    COMPLETE) echo; echo "完了"; break ;;
    FAILED|STOPPED) echo; echo "異常終了: $STATUS" >&2; exit 1 ;;
  esac
  sleep 20
done
