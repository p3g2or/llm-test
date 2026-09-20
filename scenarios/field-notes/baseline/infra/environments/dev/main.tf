locals {
  environment = "dev"
  prefix      = "${var.project_name}-${local.environment}-${var.name_suffix}"
  tags = {
    application = var.project_name
    environment = local.environment
    managed_by  = "terraform"
  }
  runtime_settings = {
    STORAGE_BACKEND           = "azure"
    AZURE_STORAGE_ACCOUNT_URL = module.storage.account_url
    AZURE_STORAGE_CONTAINER   = module.storage.container_name
    BOARD_TITLE               = trimspace(var.board_title)
  }
}

module "resource_group" {
  source   = "../../modules/resource-group"
  name     = "${local.prefix}-rg"
  location = var.location
  tags     = local.tags
}

module "storage" {
  source              = "../../modules/storage"
  name                = "${var.project_name}${local.environment}${var.name_suffix}"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  container_name      = var.container_name
  tags                = local.tags
}

module "web_app" {
  source              = "../../modules/web-app"
  name                = local.prefix
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  app_settings        = local.runtime_settings
  tags                = local.tags
}

resource "azurerm_role_assignment" "notes" {
  scope                = module.storage.container_resource_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = module.web_app.principal_id
  principal_type       = "ServicePrincipal"
}
