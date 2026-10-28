// Sightline: Azure resources for the viewer, the agent layer and (optionally) live streaming.
// Deploy with infra/deploy.sh. Resource group in uksouth, Foundry in swedencentral.

targetScope = 'resourceGroup'

@description('Prefix for resource names.')
param namePrefix string = 'sightline'

@description('Location for most resources. Defaults to the resource group location (uksouth).')
param location string = resourceGroup().location

@description('Location of the Foundry (AI Services) account and model deployment.')
param foundryLocation string = 'swedencentral'

@description('Static Web Apps Free is only offered in a few regions; westeurope is the closest to the UK.')
@allowed([
  'westeurope'
  'westus2'
  'centralus'
  'eastus2'
  'eastasia'
])
param staticWebAppLocation string = 'westeurope'

@description('Model to deploy in Foundry.')
param modelName string = 'gpt-4.1-mini'

@description('Model version.')
param modelVersion string = '2025-04-14'

@description('Deployment SKU, for example GlobalStandard, DataZoneStandard or Standard.')
param modelSku string = 'GlobalStandard'

@description('Capacity in thousands of tokens per minute. Free trial quotas are small, so keep this low.')
param modelCapacity int = 10

@description('Object id of the person running the deploy. Gets Foundry and blob access so the agents can run from a laptop. Leave empty to skip.')
param deployerPrincipalId string = ''

@description('Deploy the optional Event Hubs (Basic) and Azure Functions (Flex Consumption, Python) modules.')
param liveStreaming bool = false

param tags object = {
  app: 'sightline'
  purpose: 'inside-the-game-hackathon'
}

var suffix = uniqueString(resourceGroup().id)
var shortSuffix = substring(suffix, 0, 6)

// Role definition ids (built in)
var roles = {
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  azureAIUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0b4c9fe3'
}

// Monitoring

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs-${shortSuffix}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-appi-${shortSuffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// Identity used by hosted compute (Functions, live module)

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id-${shortSuffix}'
  location: location
  tags: tags
}

// Storage for match and history data

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(toLower('${namePrefix}${suffix}'), 24)
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource dataContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for c in [
    'matches'
    'history'
    'insights'
  ]: {
    parent: blobService
    name: c
  }
]

resource identityBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, roles.storageBlobDataReader)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataReader)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The deployer's blob contributor role was removed: new subscriptions sometimes reject it, and the app does not need it.

// Foundry: AI Services account, project and model deployment (swedencentral)

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    location: foundryLocation
    accountName: '${namePrefix}-ai-${suffix}'
    projectName: '${namePrefix}-project'
    modelName: modelName
    modelVersion: modelVersion
    modelSku: modelSku
    modelCapacity: modelCapacity
    identityPrincipalId: identity.properties.principalId
    deployerPrincipalId: deployerPrincipalId
    roleIds: roles
    tags: tags
  }
}

// Static Web App (Free) for the built viewer

resource staticSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: '${namePrefix}-web-${shortSuffix}'
  location: staticWebAppLocation
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

// Optional: Event Hubs (Basic) and Functions (Flex Consumption, Python)

module live 'modules/streaming.bicep' = if (liveStreaming) {
  name: 'streaming'
  params: {
    location: location
    namePrefix: namePrefix
    suffix: shortSuffix
    storageAccountName: storage.name
    identityId: identity.id
    identityClientId: identity.properties.clientId
    identityPrincipalId: identity.properties.principalId
    appInsightsConnectionString: appInsights.properties.ConnectionString
    foundryEndpoint: foundry.outputs.endpoint
    foundryDeployment: foundry.outputs.deploymentName
    tags: tags
  }
}

// Outputs

output staticWebAppName string = staticSite.name
output staticWebAppUrl string = 'https://${staticSite.properties.defaultHostname}'
output foundryAccountName string = foundry.outputs.accountName
output foundryEndpoint string = foundry.outputs.endpoint
output foundryProjectEndpoint string = foundry.outputs.projectEndpoint
output foundryDeployment string = foundry.outputs.deploymentName
output storageAccountName string = storage.name
output identityId string = identity.id
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output logAnalyticsWorkspaceId string = logs.id
output eventHubNamespace string = liveStreaming ? live.outputs.eventHubNamespace : ''
output functionAppUrl string = liveStreaming ? live.outputs.functionAppUrl : ''
