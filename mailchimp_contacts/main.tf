provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "sync_with_ig_rg" {
  name     = "sync-with-ig-resources"
  location = "West Europe"
}

resource "azurerm_storage_account" "sync_with_ig_sa" {
  name                     = "syncwithigstorageacct"
  resource_group_name      = azurerm_resource_group.sync_with_ig_rg.name
  location                 = azurerm_resource_group.sync_with_ig_rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_app_service_plan" "sync_with_ig_asp" {
  name                = "sync-with-ig-appserviceplan"
  location            = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name = azurerm_resource_group.sync_with_ig_rg.name
  sku {
    tier = "Consumption"
    size = "Y1"
  }
}

resource "azurerm_function_app" "sync_with_ig_fa" {
  name                       = "sync-with-ig-function"
  location                   = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name        = azurerm_resource_group.sync_with_ig_rg.name
  app_service_plan_id        = azurerm_app_service_plan.sync_with_ig_asp.id
  storage_account_name       = azurerm_storage_account.sync_with_ig_sa.name
  storage_account_access_key = azurerm_storage_account.sync_with_ig_sa.primary_access_key
  version                    = "~2"
  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME" = "python"
    "WEBSITE_RUN_FROM_PACKAGE" = "1"
  }
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_key_vault" "sync_with_ig_kv" {
  name                = "syncwithigkeyvault"
  location            = azurerm_resource_group.sync_with_ig_rg.location
  resource_group_name = azurerm_resource_group.sync_with_ig_rg.name
  tenant_id           = data.azurerm_client_config.example.tenant_id
  sku_name            = "standard"
}

resource "azurerm_key_vault_access_policy" "sync_with_ig_kv_policy" {
  key_vault_id = azurerm_key_vault.sync_with_ig_kv.id
  tenant_id    = data.azurerm_client_config.example.tenant_id
  object_id    = azurerm_function_app.sync_with_ig_fa.identity[0].principal_id

  secret_permissions = [
    "get",
    "list",
  ]
}

data "azurerm_client_config" "example" {}

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
