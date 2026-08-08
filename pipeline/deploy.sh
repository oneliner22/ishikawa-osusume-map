#!/usr/bin/env bash
# salmon-chan (central-bulwark-427114-j7) への初回デプロイ。冪等に書いてあるので再実行可。
# 前提: gcloud 認証済み / シークレット値は環境変数で渡す:
#   GITHUB_TOKEN_VALUE, XDEV_MCP_URL_VALUE (PLACES はスクリプト内で API キーを作成)
set -euo pipefail

PROJECT=central-bulwark-427114-j7
REGION=asia-northeast1
JOB=ishikawa-spots-daily
SA_NAME=ishikawa-spots-crj
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/ishikawa-spots/daily:latest"

gcloud config set project "$PROJECT"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com \
  aiplatform.googleapis.com artifactregistry.googleapis.com \
  places.googleapis.com apikeys.googleapis.com

gcloud artifacts repositories describe ishikawa-spots --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create ishikawa-spots --repository-format=docker --location="$REGION"

gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="ishikawa-spots daily ingest"
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
  --role=roles/aiplatform.user --condition=None >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
  --role=roles/secretmanager.secretAccessor --condition=None >/dev/null

upsert_secret() {  # upsert_secret NAME VALUE
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=-
  else
    printf '%s' "$2" | gcloud secrets create "$1" --data-file=-
  fi
}
upsert_secret github-token "$GITHUB_TOKEN_VALUE"
upsert_secret xdev-mcp-url "$XDEV_MCP_URL_VALUE"

if ! gcloud secrets describe places-api-key >/dev/null 2>&1; then
  KEY=$(gcloud services api-keys create --display-name="ishikawa-spots-places" \
    --api-target=service=places.googleapis.com --format="value(response.keyString)")
  upsert_secret places-api-key "$KEY"
fi

gcloud builds submit pipeline --tag "$IMAGE"

gcloud run jobs deploy "$JOB" --image "$IMAGE" --region "$REGION" \
  --service-account "$SA" --max-retries 0 --task-timeout 30m \
  --set-env-vars "GCP_PROJECT=${PROJECT},VERTEX_LOCATION=global,GITHUB_REPO=oneliner22/ishikawa-osusume-map" \
  --set-secrets "GITHUB_TOKEN=github-token:latest,XDEV_MCP_URL=xdev-mcp-url:latest,PLACES_API_KEY=places-api-key:latest"

gcloud run jobs add-iam-policy-binding "$JOB" --region "$REGION" \
  --member="serviceAccount:$SA" --role=roles/run.invoker >/dev/null

SCHED=ishikawa-spots-daily-trigger
SCHED_URI="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${JOB}:run"
if gcloud scheduler jobs describe "$SCHED" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHED" --location "$REGION" \
    --schedule "0 7 * * *" --time-zone "Asia/Tokyo" --uri "$SCHED_URI" \
    --http-method POST --oauth-service-account-email "$SA"
else
  gcloud scheduler jobs create http "$SCHED" --location "$REGION" \
    --schedule "0 7 * * *" --time-zone "Asia/Tokyo" --uri "$SCHED_URI" \
    --http-method POST --oauth-service-account-email "$SA"
fi

# ---- 日次 pending 整理ジョブ (毎日 7:40 JST、日次ジョブ完了後に走る。
# 日次ジョブは 7:00 開始 + task-timeout 30m なので 7:30 までに必ず終了している) ----
PJOB=ishikawa-spots-pending
gcloud run jobs deploy "$PJOB" --image "$IMAGE" --region "$REGION" \
  --service-account "$SA" --max-retries 0 --task-timeout 30m \
  --command python --args pending_resolver.py \
  --set-env-vars "GCP_PROJECT=${PROJECT},VERTEX_LOCATION=global,GITHUB_REPO=oneliner22/ishikawa-osusume-map" \
  --set-secrets "GITHUB_TOKEN=github-token:latest,XDEV_MCP_URL=xdev-mcp-url:latest,PLACES_API_KEY=places-api-key:latest"

PSCHED=ishikawa-spots-pending-trigger
PSCHED_URI="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${PJOB}:run"
if gcloud scheduler jobs describe "$PSCHED" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$PSCHED" --location "$REGION" \
    --schedule "40 7 * * *" --time-zone "Asia/Tokyo" --uri "$PSCHED_URI" \
    --http-method POST --oauth-service-account-email "$SA"
else
  gcloud scheduler jobs create http "$PSCHED" --location "$REGION" \
    --schedule "40 7 * * *" --time-zone "Asia/Tokyo" --uri "$PSCHED_URI" \
    --http-method POST --oauth-service-account-email "$SA"
fi

echo "done. manual run: gcloud run jobs execute $JOB --region $REGION --wait"
