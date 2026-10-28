#!/usr/bin/env bash
# Sightline: one-command deploy to Azure.
#
#   ./infra/deploy.sh
#
# Needs: az CLI (logged in), Node 18+ and npm. Optional overrides via environment:
#   RG=sightline-rg LOCATION=uksouth FOUNDRY_LOCATION=swedencentral
#   MODEL_NAME=gpt-4.1-mini MODEL_VERSION=2025-04-14 MODEL_SKU=GlobalStandard MODEL_CAPACITY=10
#   LIVE_STREAMING=true   deploy live/infra/live.bicep (Agent E) if it exists
#   STREAMING_MODULES=false   also deploy infra/modules/streaming.bicep (Event Hubs and Functions)
#   SKIP_VIEWER=false   skip building and uploading the viewer
#
# Works with the bash 3.2 that ships with macOS.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RG="${RG:-sightline-rg}"
LOCATION="${LOCATION:-uksouth}"
FOUNDRY_LOCATION="${FOUNDRY_LOCATION:-swedencentral}"
MODEL_NAME="${MODEL_NAME:-gpt-4.1-mini}"
MODEL_VERSION="${MODEL_VERSION:-2025-04-14}"
MODEL_SKU="${MODEL_SKU:-GlobalStandard}"
MODEL_CAPACITY="${MODEL_CAPACITY:-10}"
LIVE_STREAMING="${LIVE_STREAMING:-true}"
STREAMING_MODULES="${STREAMING_MODULES:-false}"
SKIP_VIEWER="${SKIP_VIEWER:-false}"
LIVE_BICEP="$ROOT/live/infra/live.json"  # precompiled from live.bicep (bicep build)

say()  { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

# 1. Azure login

say "Checking Azure login"
if ! az account show --query '{subscription:name, id:id, user:user.name}' -o table; then
  die "Not logged in. Run: az login"
fi
command -v npm >/dev/null || die "npm not found. Install Node.js 18 or later."
# templates are precompiled to ARM JSON (infra/main.json, live/infra/live.json), so no Bicep CLI is needed

# 2. Resource group

say "Creating resource group $RG in $LOCATION"
az group create --name "$RG" --location "$LOCATION" --tags app=sightline -o none

DEPLOYER_ID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"
if [ -z "$DEPLOYER_ID" ]; then
  warn "Could not read your user object id. Skipping your own Foundry and blob roles; use FOUNDRY_API_KEY locally instead."
fi

# 3. Main deployment

say "Deploying infra/main.bicep (model $MODEL_NAME $MODEL_VERSION, $MODEL_SKU, capacity $MODEL_CAPACITY, Foundry in $FOUNDRY_LOCATION)"
LOG="$(mktemp)"
set +e
az deployment group create \
  --name sightline-main \
  --resource-group "$RG" \
  --template-file infra/main.json \
  --parameters \
    foundryLocation="$FOUNDRY_LOCATION" \
    staticWebAppLocation="${SWA_LOCATION:-eastus2}" \
    modelName="$MODEL_NAME" \
    modelVersion="$MODEL_VERSION" \
    modelSku="$MODEL_SKU" \
    modelCapacity="$MODEL_CAPACITY" \
    deployerPrincipalId="$DEPLOYER_ID" \
    liveStreaming="$STREAMING_MODULES" \
  -o none 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}
set -e

if [ "$STATUS" -ne 0 ]; then
  if grep -qiE 'quota|InsufficientQuota|SkuNotSupported|DeploymentModelNotSupported|ModelNotSupported|capacity' "$LOG"; then
    cat <<EOF

================================================================
 The Foundry model deployment failed, most likely for QUOTA or
 because $MODEL_NAME ($MODEL_SKU) is not offered in $FOUNDRY_LOCATION
 on this subscription.

 Try a smaller capacity or another model, then run again
 (everything else is already deployed and is reused):

   MODEL_CAPACITY=5 ./infra/deploy.sh
   MODEL_NAME=gpt-4o-mini MODEL_VERSION=2024-07-18 ./infra/deploy.sh
   MODEL_SKU=DataZoneStandard ./infra/deploy.sh
   FOUNDRY_LOCATION=eastus2 ./infra/deploy.sh

 Check your quota:
   az cognitiveservices usage list -l $FOUNDRY_LOCATION -o table
================================================================
EOF
  fi
  die "Deployment failed (log: $LOG)"
fi

out() { az deployment group show -g "$RG" -n sightline-main --query "properties.outputs.$1.value" -o tsv; }
SWA_NAME="$(out staticWebAppName)"
SWA_URL="$(out staticWebAppUrl)"
FOUNDRY_ACCOUNT="$(out foundryAccountName)"
FOUNDRY_ENDPOINT="$(out foundryEndpoint)"
FOUNDRY_PROJECT_ENDPOINT="$(out foundryProjectEndpoint)"
FOUNDRY_DEPLOYMENT="$(out foundryDeployment)"
STORAGE="$(out storageAccountName)"
IDENTITY_ID="$(out identityId)"
IDENTITY_CLIENT_ID="$(out identityClientId)"
IDENTITY_PRINCIPAL_ID="$(out identityPrincipalId)"
APPI="$(out appInsightsConnectionString)"
LOGS_ID="$(out logAnalyticsWorkspaceId)"

# 4. Live module from Agent E (optional)

if [ "$LIVE_STREAMING" = "true" ]; then
  if [ -f "$LIVE_BICEP" ]; then
    say "Deploying live/infra/live.bicep"
    # Pass only the parameters the live module declares.
    LIVE_PARAMS=()
    for p in $(grep -E '^[[:space:]]*param[[:space:]]' "$LIVE_BICEP" | awk '{print $2}'); do
      case "$p" in
        location)                    LIVE_PARAMS+=("location=$LOCATION") ;;
        namePrefix)                  LIVE_PARAMS+=("namePrefix=sightline") ;;
        identityId)                  LIVE_PARAMS+=("identityId=$IDENTITY_ID") ;;
        identityClientId)            LIVE_PARAMS+=("identityClientId=$IDENTITY_CLIENT_ID") ;;
        identityPrincipalId)         LIVE_PARAMS+=("identityPrincipalId=$IDENTITY_PRINCIPAL_ID") ;;
        storageAccountName)          LIVE_PARAMS+=("storageAccountName=$STORAGE") ;;
        appInsightsConnectionString) LIVE_PARAMS+=("appInsightsConnectionString=$APPI") ;;
        logAnalyticsWorkspaceId)     LIVE_PARAMS+=("logAnalyticsWorkspaceId=$LOGS_ID") ;;
        foundryEndpoint)             LIVE_PARAMS+=("foundryEndpoint=$FOUNDRY_ENDPOINT") ;;
        foundryDeployment)           LIVE_PARAMS+=("foundryDeployment=$FOUNDRY_DEPLOYMENT") ;;
        staticWebAppName)            LIVE_PARAMS+=("staticWebAppName=$SWA_NAME") ;;
      esac
    done
    if [ ${#LIVE_PARAMS[@]} -gt 0 ]; then
      az deployment group create --name sightline-live --resource-group "$RG" \
        --template-file "$LIVE_BICEP" --parameters "${LIVE_PARAMS[@]}" -o none \
        || warn "live.bicep failed. The core app still works; rerun with LIVE_STREAMING=false to skip it."
    else
      az deployment group create --name sightline-live --resource-group "$RG" \
        --template-file "$LIVE_BICEP" -o none \
        || warn "live.bicep failed. The core app still works; rerun with LIVE_STREAMING=false to skip it."
    fi
  else
    warn "live/infra/live.bicep not found yet, skipping the live module. The viewer runs on precomputed data."
  fi
fi

# 5. Match and history data to Storage (best effort)

say "Uploading sample match and history data to $STORAGE"
az storage blob upload-batch --auth-mode login --account-name "$STORAGE" \
  -d matches -s matchgen/sample/demo_seed587 --destination-path demo_seed587 --overwrite -o none 2>/dev/null \
  && az storage blob upload-batch --auth-mode login --account-name "$STORAGE" \
  -d history -s matchgen/sample/history --overwrite -o none 2>/dev/null \
  || warn "Blob upload skipped (role assignment may still be propagating; rerun later). The viewer does not depend on it."

# 6. Build and upload the viewer

if [ "$SKIP_VIEWER" != "true" ]; then
  say "Building the viewer"
  (cd viewer && npm ci && npm run build)
  cp infra/staticwebapp.config.json viewer/dist/staticwebapp.config.json

  say "Uploading viewer/dist to Static Web App $SWA_NAME"
  SWA_TOKEN="$(az staticwebapp secrets list -n "$SWA_NAME" -g "$RG" --query properties.apiKey -o tsv)"
  npx --yes @azure/static-web-apps-cli deploy viewer/dist \
    --deployment-token "$SWA_TOKEN" --env production
fi

# 7. Summary

say "Done"
echo "Viewer:            $SWA_URL"
echo "Foundry endpoint:  $FOUNDRY_ENDPOINT"
echo "Foundry project:   $FOUNDRY_PROJECT_ENDPOINT"
echo "Model deployment:  $FOUNDRY_DEPLOYMENT"
if [ "$LIVE_STREAMING" = "true" ] && [ -f "$LIVE_BICEP" ]; then
  for o in webPubSubEndpoint functionAppUrl claimsApiUrl; do
    v="$(az deployment group show -g "$RG" -n sightline-live --query "properties.outputs.$o.value" -o tsv 2>/dev/null || true)"
    if [ -n "$v" ]; then echo "Live $o: $v"; fi
  done
fi

cat <<EOF

Paste these to run the agents live from this terminal:

export FOUNDRY_ENDPOINT="$FOUNDRY_ENDPOINT"
export FOUNDRY_PROJECT_ENDPOINT="$FOUNDRY_PROJECT_ENDPOINT"
export FOUNDRY_DEPLOYMENT="$FOUNDRY_DEPLOYMENT"

Optional, if Entra auth is not ready yet (role assignments can take a few minutes):

export FOUNDRY_API_KEY="\$(az cognitiveservices account keys list -g $RG -n $FOUNDRY_ACCOUNT --query key1 -o tsv)"
EOF
