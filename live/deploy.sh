#!/usr/bin/env bash
# Deploy the Sightline live pipeline into an existing resource group and start a replay.
#
#   ./live/deploy.sh <resource-group> [foundry-account-name]
#
# Needs: az (logged in), python 3.10+, and Azure Functions Core Tools (`func`) if available
# (falls back to `az functionapp deployment source config-zip`).
# Env overrides: PREFIX (sightline), MATCH (matchgen/sample/demo_seed587), SPEED (30),
#   SKIP_INFRA=1 (reuse the last deployment), SKIP_PUBLISH=1, SKIP_REPLAY=1.
set -euo pipefail

RG="${1:?usage: live/deploy.sh <resource-group> [foundry-account-name]}"
FOUNDRY="${2:-}"
PREFIX="${PREFIX:-sightline}"
SPEED="${SPEED:-30}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MATCH="${MATCH:-$ROOT/matchgen/sample/demo_seed587}"
DEPLOYMENT="sightline-live"

cd "$ROOT"

if [[ "${SKIP_INFRA:-0}" != "1" ]]; then
  echo "== Deploying live/infra/live.bicep into $RG"
  az deployment group create -g "$RG" -n "$DEPLOYMENT" -f live/infra/live.bicep \
    -p prefix="$PREFIX" foundryAccountName="$FOUNDRY" -o none
fi

out() { az deployment group show -g "$RG" -n "$DEPLOYMENT" --query "properties.outputs.$1.value" -o tsv; }
APP="$(out functionAppName)"
APP_URL="$(out functionAppUrl)"
EHNS="$(out eventHubsNamespace)"
EH="$(out eventHubName)"
echo "   function app: $APP ($APP_URL)"

if [[ "${SKIP_PUBLISH:-0}" != "1" ]]; then
  echo "== Staging and publishing the functions"
  BUILD="$(python3 live/functions/stage.py --match "$MATCH")"
  if command -v func >/dev/null 2>&1; then
    (cd "$BUILD" && func azure functionapp publish "$APP" --python)
  else
    ZIP="$(mktemp -d)/live-functions.zip"
    (cd "$BUILD" && zip -qr "$ZIP" . -x '*__pycache__*')
    az functionapp deployment source config-zip -g "$RG" -n "$APP" --src "$ZIP" --build-remote true -o none
  fi
  echo "   waiting 30 s for role assignments and the host to settle"
  sleep 30
fi

echo
echo "Viewer: cd viewer && npm run dev, then open http://localhost:5173/#live=$APP_URL"
echo "Negotiate check: curl '$APP_URL/api/negotiate?match_id=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['match_id'])" "$MATCH/match.json")'"
echo

if [[ "${SKIP_REPLAY:-0}" != "1" ]]; then
  echo "== Replaying $(basename "$MATCH") into Event Hubs at speed $SPEED (Ctrl+C to stop)"
  python3 -c "import azure.eventhub" 2>/dev/null || python3 -m pip install -q "azure-eventhub>=5.11"
  # matchgen's Event Hubs sink takes a connection string. It is read at run time and never stored;
  # the Function App itself only uses its managed identity.
  EVENTHUB_CONNECTION_STRING="$(az eventhubs namespace authorization-rule keys list -g "$RG" \
    --namespace-name "$EHNS" -n RootManageSharedAccessKey --query primaryConnectionString -o tsv)"
  export EVENTHUB_CONNECTION_STRING EVENTHUB_NAME="$EH"
  (cd "$ROOT/matchgen" && python3 -m matchgen stream --dir "$MATCH" --speed "$SPEED" --sink eventhub)
fi
