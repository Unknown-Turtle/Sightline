#!/usr/bin/env bash
# Runs the agents against the deployed Foundry model, then redeploys the viewer with the results.
set -e
cd "$(dirname "$0")"
echo "==> Reading Foundry settings"
export FOUNDRY_ENDPOINT="$(az deployment group show -g sightline-rg -n sightline-main --query properties.outputs.foundryEndpoint.value -o tsv)"
export FOUNDRY_DEPLOYMENT="$(az deployment group show -g sightline-rg -n sightline-main --query properties.outputs.foundryDeployment.value -o tsv)"
ACCT="$(az deployment group show -g sightline-rg -n sightline-main --query properties.outputs.foundryAccountName.value -o tsv)"
export FOUNDRY_API_KEY="$(az cognitiveservices account keys list -g sightline-rg -n "$ACCT" --query key1 -o tsv)"
SWA_TOKEN="$(az staticwebapp secrets list -n sightline-web-3n5v6w -g sightline-rg --query properties.apiKey -o tsv)"
echo "Endpoint: $FOUNDRY_ENDPOINT  Deployment: $FOUNDRY_DEPLOYMENT"
echo "==> Installing agent requirements"
python3 -m pip install -q -r agents/requirements.txt || python3 -m pip install -q --break-system-packages -r agents/requirements.txt
echo "==> Building AI insights (live)"
python3 -m agents build --match matchgen/sample/demo_seed587 --history matchgen/sample/history --out viewer/public/data/insights.json
echo "==> Translating"
python3 -m agents.extras translate || echo "[warn] translation step failed, English only"
echo "==> Building the viewer"
(cd viewer && npm run build)
cp infra/staticwebapp.config.json viewer/dist/ 2>/dev/null || true
echo "==> Uploading to Azure"
npx --yes @azure/static-web-apps-cli deploy viewer/dist --deployment-token "$SWA_TOKEN" --env production
echo "==> Done. Mode in insights.json:"
python3 -c "import json;d=json.load(open('viewer/public/data/insights.json'));print(d.get('mode'), d.get('model'), len(d['items']), 'items')"
