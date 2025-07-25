terraform {
  backend "azurerm" {
    resource_group_name  = "rg-botgc-shared"
    storage_account_name = "sabotgcmain"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}

provider "azurerm" {
  features {}
}

data "azurerm_client_config" "example" {}

resource "azurerm_resource_group" "sync_with_ig_rg" {
  name     = "rg-${var.project_name}-${var.environment}"
  location = "West Europe"
}

data "azurerm_storage_account" "sync_with_ig_sa" {
  name                = "sabotgcmain"
  resource_group_name = "rg-botgc-shared"
}

resource "azurerm_storage_container" "data" {
  name                  = "data"
  storage_account_name  = data.azurerm_storage_account.sync_with_ig_sa.name
  container_access_type = "private"
}

resource "azurerm_service_plan" "sync_with_ig_asp" {
  name                = "asp-${var.project_name}-${var.environment}"
  location            = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name = azurerm_resource_group.sync_with_ig_rg.name
  os_type             = "Linux"
  sku_name            = "Y1" # This is the consumption plan for cost-effectiveness
}

resource "azurerm_linux_function_app" "sync_with_ig_fa" {
  name                        = "fa-${var.project_name}-${var.environment}"
  location                    = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name         = azurerm_resource_group.sync_with_ig_rg.name
  service_plan_id             = azurerm_service_plan.sync_with_ig_asp.id
  storage_account_name        = data.azurerm_storage_account.sync_with_ig_sa.name
  storage_account_access_key  = data.azurerm_storage_account.sync_with_ig_sa.primary_access_key
  functions_extension_version = "~4"
  app_settings = {
    "APPINSIGHTS_INSTRUMENTATIONKEY"        = azurerm_application_insights.app_insights.instrumentation_key
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.app_insights.connection_string
    "SCM_DO_BUILD_DURING_DEPLOYMENT"        = true
    "WEBSITE_RUN_FROM_PACKAGE"              = "1"
    "MEMBER_ID"                             = var.member_id
    "MEMBER_PIN"                            = var.member_pin
    "ADMIN_PASSWORD"                        = var.admin_password
    "MAILCHIMP_API_KEY"                     = var.mailchimp_api_key
    "MAILCHIMP_SERVER"                      = var.mailchimp_server
    "MAILCHIMP_AUDIENCE_ID"                 = var.mailchimp_audience_id
    "PYTHONPATH"                            = "/home/site/wwwroot/common"
    "DATA_CONTAINER_CONNECTION_STRING"      = data.azurerm_storage_account.sync_with_ig_sa.primary_connection_string
  }

  site_config {
    application_stack {
      python_version = "3.8"
    }
  }
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_key_vault" "sync_with_ig_kv" {
  name                = "kv-${var.project_name}-${var.environment}"
  location            = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name = azurerm_resource_group.sync_with_ig_rg.name
  tenant_id           = data.azurerm_client_config.example.tenant_id
  sku_name            = "standard"
}

resource "azurerm_key_vault_access_policy" "sync_with_ig_kv_policy" {
  key_vault_id = azurerm_key_vault.sync_with_ig_kv.id
  tenant_id    = data.azurerm_client_config.example.tenant_id
  object_id    = azurerm_linux_function_app.sync_with_ig_fa.identity[0].principal_id

  secret_permissions = [
    "Get",
    "List",
    "Set"
  ]
}

resource "azurerm_key_vault_access_policy" "terraform_sp_kv_policy" {
  key_vault_id = azurerm_key_vault.sync_with_ig_kv.id
  tenant_id    = data.azurerm_client_config.example.tenant_id
  object_id    = data.azurerm_client_config.example.object_id

  secret_permissions = [
    "Get",
    "List",
    "Set"
  ]
}

resource "azurerm_key_vault_secret" "member_id" {
  name         = "member-id"
  value        = var.member_id
  key_vault_id = azurerm_key_vault.sync_with_ig_kv.id
}

resource "azurerm_key_vault_secret" "member_pin" {
  name         = "member-pin"
  value        = var.member_pin
  key_vault_id = azurerm_key_vault.sync_with_ig_kv.id
}

resource "azurerm_key_vault_secret" "admin_password" {
  name         = "admin-password"
  value        = var.admin_password
  key_vault_id = azurerm_key_vault.sync_with_ig_kv.id
}

resource "azurerm_key_vault_secret" "mailchimp_api_key" {
  name         = "mailchimp-api-key"
  value        = var.mailchimp_api_key
  key_vault_id = azurerm_key_vault.sync_with_ig_kv.id
}

resource "azurerm_application_insights" "app_insights" {
  name                = "app-insights-${var.project_name}-${var.environment}"
  location            = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name = azurerm_resource_group.sync_with_ig_rg.name
  application_type    = "web"
  workspace_id        = "/subscriptions/a36e907d-02d3-493e-a054-93ab237526c3/resourceGroups/ai_app-insights-botgcint-prd_853663e3-1e09-4a9e-b3ca-4747f38a0115_managed/providers/Microsoft.OperationalInsights/workspaces/managed-app-insights-botgcint-prd-ws"
}

output "function_app_name" {
  value = azurerm_linux_function_app.sync_with_ig_fa.name
}
