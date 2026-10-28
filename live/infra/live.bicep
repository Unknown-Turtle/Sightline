// Sightline live pipeline: Event Hubs (Basic) -> Function App (Flex Consumption) -> Web PubSub (Free).
// Deploy into an existing resource group:
//   az deployment group create -g <rg> -f live/infra/live.bicep -p foundryAccountName=<foundry account>
// The Function App uses its system-assigned identity for everything (no keys in app settings).

@description('Short prefix for resource names (lowercase letters and digits).')
@minLength(3)
@maxLength(12)
param prefix string = 'sightline'

param location string = resourceGroup().location

@description('Name of an existing Azure AI Foundry (Cognitive Services) account in this resource group. Empty skips the role assignment.')
param foundryAccountName string = ''

@description('Event hub the matchgen replay sends to.')
param eventHubName string = 'match-events'

@description('Web PubSub hub the viewers connect to.')
param webPubSubHub string = 'match'

@description('Match whose match.json the app loads when a client does not name one.')
param defaultMatchId string = 'm_seed587'

@description('Allowed browser origins for negotiate and claims.')
param corsOrigins array = ['*']

var suffix = uniqueString(resourceGroup().id, prefix)
var storageName = take('${prefix}live${suffix}', 24)
var deployContainer = 'app-package'

// Built-in role definition IDs
var roles = {
  eventHubsDataReceiver: 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'
  webPubSubServiceOwner: '12cf5a90-567b-43ae-8102-96cf46c7d9b4'
  azureAiUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f988ec8c8f8'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}

resource ehns 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: '${prefix}-ehns-${suffix}'
  location: location
  sku: { name: 'Basic', tier: 'Basic', capacity: 1 }
  properties: { minimumTlsVersion: '1.2' }
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: ehns
  name: eventHubName
  properties: { partitionCount: 2, messageRetentionInDays: 1 }
}

resource wps 'Microsoft.SignalRService/webPubSub@2024-03-01' = {
  name: '${prefix}-wps-${suffix}'
  location: location
  sku: { name: 'Free_F1', tier: 'Free', capacity: 1 }
  properties: { publicNetworkAccess: 'Enabled' }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource packages 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: deployContainer
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${prefix}-plan-${suffix}'
  location: location
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2024-04-01' = {
  name: '${prefix}-live-${suffix}'
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deployContainer}'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: 40, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.11' }
    }
    siteConfig: {
      cors: { allowedOrigins: corsOrigins }
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'EventHubConnection__fullyQualifiedNamespace', value: '${ehns.name}.servicebus.windows.net' }
        { name: 'EventHubConnection__credential', value: 'managedidentity' }
        { name: 'EVENTHUB_NAME', value: eventHubName }
        { name: 'WEBPUBSUB_ENDPOINT', value: 'https://${wps.properties.hostName}' }
        { name: 'WEBPUBSUB_HUB', value: webPubSubHub }
        { name: 'DEFAULT_MATCH_ID', value: defaultMatchId }
        { name: 'FOUNDRY_ACCOUNT_NAME', value: foundryAccountName }
      ]
    }
  }
  dependsOn: [packages]
}

resource raEventHubs 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hub.id, func.id, roles.eventHubsDataReceiver)
  scope: hub
  properties: {
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsDataReceiver)
  }
}

resource raWebPubSub 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(wps.id, func.id, roles.webPubSubServiceOwner)
  scope: wps
  properties: {
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.webPubSubServiceOwner)
  }
}

resource raStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in [
  roles.storageBlobDataOwner
  roles.storageQueueDataContributor
  roles.storageTableDataContributor
]: {
  name: guid(storage.id, func.id, r)
  scope: storage
  properties: {
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
  }
}]

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!empty(foundryAccountName)) {
  name: empty(foundryAccountName) ? 'unused' : foundryAccountName
}

resource raFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(foundryAccountName)) {
  name: guid(resourceGroup().id, foundryAccountName, func.id, roles.azureAiUser)
  scope: foundry
  properties: {
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiUser)
  }
}

output functionAppName string = func.name
output functionAppUrl string = 'https://${func.properties.defaultHostName}'
output eventHubsNamespace string = ehns.name
output eventHubName string = hub.name
output webPubSubName string = wps.name
output webPubSubHub string = webPubSubHub
