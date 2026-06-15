#!/bin/bash
set -e

# =============================================================================
# Cloud Run Deployment Script for SHOPLINE Sync Service
# Usage: ./deploy.sh [development|production]
#
# Secrets are managed via Google Cloud Secret Manager (not .env).
# Mirrors app-webhook/deploy.sh. The Cloud Run service name `shopline-sync`
# was reserved 2026-06-11 (placeholder hello image); this replaces it.
# =============================================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

ENVIRONMENT="${1:-development}"
if [ "$ENVIRONMENT" != "development" ] && [ "$ENVIRONMENT" != "production" ]; then
    echo -e "${RED}Error: Invalid environment '$ENVIRONMENT'${NC}"
    echo "Usage: $0 [development|production]"
    exit 1
fi

echo -e "${BLUE}=== SHOPLINE Sync Service - Cloud Run Deployment ===${NC}"
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"

PROJECT_ID="${GCP_PROJECT_ID:-shopify-473015}"
REGION="${GCP_REGION:-us-central1}"

if [ "$ENVIRONMENT" = "development" ]; then
    SERVICE_NAME="${SERVICE_NAME:-shopline-sync}"
    MEMORY="512Mi"; CPU="1"; MIN_INSTANCES="0"; MAX_INSTANCES="10"
    LOG_LEVEL="INFO"; DEBUG="false"; CONCURRENCY=""
    DB_DSN_SECRET="DB_DSN"
    API_KEY_SECRET="API_KEY"
    SHOPLINE_API_KEY_SECRET="SHOPLINE_API_KEY"
    SHOPLINE_API_SECRET_SECRET="SHOPLINE_API_SECRET"
    SHOPLINE_WEBHOOK_SECRET_SECRET="SHOPLINE_WEBHOOK_SECRET"
    OAUTH_REDIRECT_URL_SECRET="SHOPLINE_OAUTH_REDIRECT_URL"
    # Where /api/oauth/callback redirects the browser after a successful connect
    # (the chekoutai builder's AI Persona page reads ?status/merchant_id/shop_handle).
    # Production-forward: a single shopline-sync backend serves both frontend envs,
    # so we always land on the prod builder (app.chekout.ai) for now.
    FRONTEND_RETURN_URL="https://app.chekout.ai/ai-agent"
else  # production
    SERVICE_NAME="shopline-sync"
    MEMORY="1Gi"; CPU="2"; MIN_INSTANCES="1"; MAX_INSTANCES="100"
    LOG_LEVEL="WARNING"; DEBUG="false"; CONCURRENCY="80"
    DB_DSN_SECRET="DB_DSN_PROD"
    API_KEY_SECRET="API_KEY_PROD"
    SHOPLINE_API_KEY_SECRET="SHOPLINE_API_KEY_PROD"
    SHOPLINE_API_SECRET_SECRET="SHOPLINE_API_SECRET_PROD"
    SHOPLINE_WEBHOOK_SECRET_SECRET="SHOPLINE_WEBHOOK_SECRET_PROD"
    OAUTH_REDIRECT_URL_SECRET="SHOPLINE_OAUTH_REDIRECT_URL_PROD"
    FRONTEND_RETURN_URL="https://app.chekout.ai/ai-agent"
fi

IMAGE_NAME="gcr.io/${PROJECT_ID}/shopline-sync"

if [ "$ENVIRONMENT" = "production" ]; then
    echo -e "${RED}WARNING: You are about to deploy to PRODUCTION!${NC}"
    read -p "Type 'yes' to confirm production deployment: " -r
    echo
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo -e "${YELLOW}Deployment cancelled.${NC}"; exit 0
    fi
fi

if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed.${NC}"; exit 1
fi

echo ""
echo -e "${BLUE}Deployment Configuration:${NC}"
echo "   Environment:  $ENVIRONMENT"
echo "   Service:      $SERVICE_NAME"
echo "   Project:      $PROJECT_ID"
echo "   Region:       $REGION"
echo "   Resources:    ${MEMORY} RAM, ${CPU} CPU"
echo ""

# Non-secret env vars via temp YAML (avoids comma-escaping issues)
ENV_VARS_FILE=$(mktemp /tmp/cloudrun-env-XXXXXX.yaml)
cat > "${ENV_VARS_FILE}" <<EOF
ENVIRONMENT: "${ENVIRONMENT}"
DEBUG: "${DEBUG}"
LOG_LEVEL: "${LOG_LEVEL}"
SHOPLINE_SCOPES: "${SHOPLINE_SCOPES:-read_products,read_orders,read_content,read_page,read_shop_policy}"
SHOPLINE_API_VERSION: "${SHOPLINE_API_VERSION:-v20260601}"
ENABLE_SCHEDULER: "${ENABLE_SCHEDULER:-true}"
RECONCILIATION_HOUR: "${RECONCILIATION_HOUR:-2}"
RECONCILIATION_MINUTE: "${RECONCILIATION_MINUTE:-0}"
GCP_PROJECT_ID: "${PROJECT_ID}"
GCP_REGION: "${REGION}"
ENABLE_EMBEDDINGS: "${ENABLE_EMBEDDINGS:-true}"
SHOPLINE_FRONTEND_RETURN_URL: "${FRONTEND_RETURN_URL}"
EOF

SECRETS="DB_DSN=${DB_DSN_SECRET}:latest"
SECRETS="${SECRETS},ENCRYPTION_KEY=ENCRYPTION_KEY:latest"
SECRETS="${SECRETS},API_KEY=${API_KEY_SECRET}:latest"
SECRETS="${SECRETS},SHOPLINE_API_KEY=${SHOPLINE_API_KEY_SECRET}:latest"
SECRETS="${SECRETS},SHOPLINE_API_SECRET=${SHOPLINE_API_SECRET_SECRET}:latest"
SECRETS="${SECRETS},SHOPLINE_WEBHOOK_SECRET=${SHOPLINE_WEBHOOK_SECRET_SECRET}:latest"
SECRETS="${SECRETS},SHOPLINE_OAUTH_REDIRECT_URL=${OAUTH_REDIRECT_URL_SECRET}:latest"

echo -e "${YELLOW}Setting project to: ${PROJECT_ID}${NC}"
gcloud config set project ${PROJECT_ID}

echo -e "${YELLOW}Building and pushing Docker image...${NC}"
gcloud builds submit --tag ${IMAGE_NAME}:latest --project ${PROJECT_ID}

echo -e "${YELLOW}Deploying to Cloud Run...${NC}"
DEPLOY_CMD="gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME}:latest \
    --platform managed \
    --region ${REGION} \
    --port 8000 \
    --memory ${MEMORY} \
    --cpu ${CPU} \
    --timeout 300 \
    --min-instances ${MIN_INSTANCES} \
    --max-instances ${MAX_INSTANCES} \
    --allow-unauthenticated \
    --env-vars-file ${ENV_VARS_FILE} \
    --set-secrets ${SECRETS}"
if [ -n "$CONCURRENCY" ]; then
    DEPLOY_CMD="${DEPLOY_CMD} --concurrency ${CONCURRENCY}"
fi
eval ${DEPLOY_CMD}
rm -f "${ENV_VARS_FILE}"

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region=${REGION} --project=${PROJECT_ID} --format='value(status.url)' 2>/dev/null)

echo -e "${YELLOW}Verifying deployment...${NC}"
echo "Service URL: ${SERVICE_URL}"
sleep 10
if curl -f "${SERVICE_URL}/health" > /dev/null 2>&1; then
    echo -e "${GREEN}Health check passed!${NC}"
else
    echo -e "${YELLOW}Health check endpoint not available yet${NC}"
fi

echo ""
echo -e "${GREEN}=============================================="
echo "Deployment Complete!"
echo "Service:  ${SERVICE_NAME}"
echo "URL:      ${SERVICE_URL}"
echo "==============================================${NC}"
