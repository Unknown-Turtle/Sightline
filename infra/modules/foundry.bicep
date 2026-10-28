// Microsoft Foundry: an AI Services account with project management, one project and one model deployment.

param location string
param accountName string
param projectName string
param modelName string
param modelVersion string
param modelSku string
param modelCapacity int
param identityPrincipalId string
param deployerPrincipalId string
param roleIds object
param tags object

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Sightline'
    description: 'Analyst, trivia, narrator and checker agents for Sightline match intelligence.'
  }
}

// One deployment, created after the project so the account is not asked for two changes at once.
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: modelName
  dependsOn: [
    project
  ]
  sku: {
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// Managed identity: call models (Cognitive Services OpenAI User) and use the project (Azure AI User)
resource identityOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, identityPrincipalId, roleIds.cognitiveServicesOpenAIUser)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.cognitiveServicesOpenAIUser)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource identityAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, identityPrincipalId, roleIds.azureAIUser)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.azureAIUser)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// The person deploying, so the agents can run from a laptop with az login
resource deployerOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(account.id, deployerPrincipalId, roleIds.cognitiveServicesOpenAIUser)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.cognitiveServicesOpenAIUser)
    principalId: deployerPrincipalId
    principalType: 'User'
  }
}

resource deployerAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(account.id, deployerPrincipalId, roleIds.azureAIUser)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.azureAIUser)
    principalId: deployerPrincipalId
    principalType: 'User'
  }
}

output accountName string = account.name
output endpoint string = account.properties.endpoint
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
output deploymentName string = modelDeployment.name
