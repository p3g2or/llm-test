terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.64.0"
    }
  }
}

resource "azurerm_service_plan" "this" {
  name                = "${var.name}-plan"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "B1"
  tags                = var.tags
}

resource "azurerm_linux_web_app" "this" {
  name                                           = var.name
  resource_group_name                            = var.resource_group_name
  location                                       = var.location
  service_plan_id                                = azurerm_service_plan.this.id
  https_only                                     = true
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  tags                                           = var.tags

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on                         = true
    minimum_tls_version               = "1.2"
    ftps_state                        = "Disabled"
    health_check_path                 = "/api/health"
    health_check_eviction_time_in_min = 5
    app_command_line                  = "python -m uvicorn fieldnotes.main:app --host 0.0.0.0 --port 8000"

    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = merge(var.app_settings, {
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
  })
}
