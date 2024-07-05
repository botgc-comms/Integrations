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

resource "azurerm_service_plan" "sync_with_ig_asp" {
  name                = "asp-${var.project_name}-${var.environment}"
  location            = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name = azurerm_resource_group.sync_with_ig_rg.name
  os_type             = "Linux"
  sku_name            = "Y1" # This is the consumption plan for cost-effectiveness
}

resource "azurerm_linux_function_app" "sync_with_ig_fa" {
  name                       = "fa-${var.project_name}-${var.environment}"
  location                   = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name        = azurerm_resource_group.sync_with_ig_rg.name
  service_plan_id            = azurerm_service_plan.sync_with_ig_asp.id
  storage_account_name       = data.azurerm_storage_account.sync_with_ig_sa.name
  storage_account_access_key = data.azurerm_storage_account.sync_with_ig_sa.primary_access_key

  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME" = "python"
    "WEBSITE_RUN_FROM_PACKAGE" = "1"
  }
  identity {
    type = "SystemAssigned"
  }

  site_config {}
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

output "function_app_name" {
  value = azurerm_linux_function_app.sync_with_ig_fa.name
}
