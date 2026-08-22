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

# 連続で何回 API 失敗を許容するか(20秒間隔なので 15回 = 5分)
MAX_FAILURES=15
failures=0

while true; do
  # 一時的な失敗では取り込みがサーバ側で継続しているので待って再試行する。
  # ただし連続で失敗し続ける場合は認証切れなどの恒久的な問題なので、黙って待ち続けない。
  if ! ERR=$(aws bedrock-agent get-ingestion-job \
    --knowledge-base-id "$KB" --data-source-id "$DS" --ingestion-job-id "$JOB" --region "$REGION" \
    --query 'ingestionJob.[status,statistics.numberOfDocumentsScanned,statistics.numberOfNewDocumentsIndexed,statistics.numberOfDocumentsFailed]' \
    --output text 2>&1); then
    failures=$((failures + 1))
    if [ "$failures" -ge "$MAX_FAILURES" ]; then
      echo
      echo "取り込み状態の取得に $MAX_FAILURES 回連続で失敗しました。監視を中止します。" >&2
      echo "最後のエラー: $ERR" >&2
      echo "認証が切れている可能性があります: aws sso login --sso-session ga" >&2
      echo "取り込みジョブ $JOB はサーバ側で継続している可能性があります。次で状態を確認してください:" >&2
      echo "  aws bedrock-agent get-ingestion-job --knowledge-base-id $KB --data-source-id $DS --ingestion-job-id $JOB --region $REGION" >&2
      exit 1
    fi
    sleep 20
    continue
  fi
  OUT=$ERR
  failures=0
  read -r STATUS SCANNED INDEXED FAILED <<< "$OUT"
  printf '\r%s  scanned=%s indexed=%s failed=%s   ' "$STATUS" "$SCANNED" "$INDEXED" "$FAILED"
  case "$STATUS" in
    COMPLETE) echo; echo "完了"; break ;;
    FAILED|STOPPED) echo; echo "異常終了: $STATUS" >&2; exit 1 ;;
  esac
  sleep 20
done
