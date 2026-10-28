# Deploying Sightline

## One command

```bash
az login
./infra/deploy.sh
```

Requirements on the machine: Azure CLI (Bicep is installed automatically), Node.js 18 or later with npm. The script works with the bash that ships with macOS.

## What it does

1. Checks `az account show`
2. Creates the resource group `sightline-rg` in `uksouth`
3. Deploys `infra/main.bicep`:
   - Static Web App (Free) in `westeurope`, because the Free tier is not offered in UK South
   - Microsoft Foundry in `swedencentral`: an AI Services account with project management enabled, a project `sightline-project` and one model deployment (default `gpt-4.1-mini`, version `2025-04-14`, `GlobalStandard`, 10K tokens per minute)
   - Storage account with `matches`, `history` and `insights` containers
   - Log Analytics workspace and Application Insights
   - User-assigned managed identity with Cognitive Services OpenAI User and Azure AI User on Foundry, and Storage Blob Data Reader on Storage
   - Your own user also gets Cognitive Services OpenAI User, Azure AI User and Storage Blob Data Contributor, so the agents run from your laptop with `az login` and no keys
   - Optional (`STREAMING_MODULES=true`): Event Hubs Basic with a `match-events` hub and a Python Function App on Flex Consumption, wired to the identity
4. Deploys `live/infra/live.bicep` from the live pipeline if the file exists (on by default, `LIVE_STREAMING=false` to skip), passing only the parameters it declares (see `docs/insights-contract.md`)
5. Uploads `matchgen/sample` to Storage (best effort)
6. Builds the viewer and uploads `viewer/dist` with the Static Web Apps CLI, adding `infra/staticwebapp.config.json`
7. Prints the URL and the `export FOUNDRY_...` lines

Running it again is safe: every step is idempotent.

## Options

| Variable | Default | Use |
| --- | --- | --- |
| `RG` | `sightline-rg` | Resource group name |
| `LOCATION` | `uksouth` | Region for everything except Foundry and the Static Web App |
| `FOUNDRY_LOCATION` | `swedencentral` | Foundry region |
| `MODEL_NAME` | `gpt-4.1-mini` | Model |
| `MODEL_VERSION` | `2025-04-14` | Model version |
| `MODEL_SKU` | `GlobalStandard` | Deployment type |
| `MODEL_CAPACITY` | `10` | Thousands of tokens per minute |
| `LIVE_STREAMING` | `true` | Deploy `live/infra/live.bicep` if present |
| `STREAMING_MODULES` | `false` | Deploy the Event Hubs and Functions modules in `infra/modules/streaming.bicep` |
| `SKIP_VIEWER` | `false` | Skip the viewer build and upload |

## If the model deployment fails

Free trial subscriptions have small model quotas. The script spots quota errors and suggests a fix. In order of what usually works:

```bash
MODEL_CAPACITY=5 ./infra/deploy.sh
MODEL_NAME=gpt-4o-mini MODEL_VERSION=2024-07-18 ./infra/deploy.sh
MODEL_SKU=DataZoneStandard ./infra/deploy.sh
az cognitiveservices usage list -l swedencentral -o table   # see what you have
```

## Running the agents live

Paste the `export` lines the script prints. If you see 401 or 403 errors in the first few minutes, the role assignments are still propagating: wait, or use the printed `FOUNDRY_API_KEY` line.

## Cost

With the defaults: the Static Web App is free, Storage and monitoring cost pennies at demo scale, and the model is pay per token. Event Hubs Basic and Flex Consumption are only created on request. Delete everything with:

```bash
az group delete -n sightline-rg --yes --no-wait
```

## Files

```
infra/main.bicep                 everything except the optional live path
infra/modules/foundry.bicep      AI Services account, project, model deployment, roles
infra/modules/streaming.bicep    Event Hubs Basic and Functions Flex Consumption (optional)
infra/staticwebapp.config.json   MIME types and SPA fallback for the viewer
infra/deploy.sh                  the one command
```
