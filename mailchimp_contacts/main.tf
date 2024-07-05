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
}
