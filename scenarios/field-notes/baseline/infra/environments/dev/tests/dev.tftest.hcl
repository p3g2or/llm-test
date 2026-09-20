mock_provider "azurerm" {
  mock_resource "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg/providers/Microsoft.Storage/storageAccounts/testnotes"
      primary_blob_endpoint = "https://testnotes.blob.core.windows.net/"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg/providers/Microsoft.Storage/storageAccounts/testnotes/blobServices/default/containers/notes"
    }
  }
  mock_resource "azurerm_service_plan" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg/providers/Microsoft.Web/serverFarms/test-plan"
    }
  }
  mock_resource "azurerm_linux_web_app" {
    defaults = {
      default_hostname = "test-notes.azurewebsites.net"
      identity = {
        type         = "SystemAssigned"
        principal_id = "11111111-1111-1111-1111-111111111111"
        tenant_id    = "22222222-2222-2222-2222-222222222222"
      }
    }
  }
}

variables {
  name_suffix = "test1234"
  board_title = "Team Notes"
}

run "dev_wiring" {
  command = apply

  assert {
    condition     = output.runtime_settings.STORAGE_BACKEND == "azure"
    error_message = "Dev must use Azure storage."
  }
  assert {
    condition     = output.runtime_settings.AZURE_STORAGE_ACCOUNT_URL == "https://testnotes.blob.core.windows.net/"
    error_message = "The storage endpoint must reach the application."
  }
  assert {
    condition     = output.runtime_settings.AZURE_STORAGE_CONTAINER == "notes" && output.runtime_settings.BOARD_TITLE == "Team Notes"
    error_message = "Runtime settings must match the configured notebook."
  }
  assert {
    condition     = azurerm_role_assignment.notes.principal_id == module.web_app.principal_id && azurerm_role_assignment.notes.scope == module.storage.container_resource_id
    error_message = "The app identity must receive access to its note container."
  }
  assert {
    condition     = output.app_url == "https://test-notes.azurewebsites.net"
    error_message = "Expose the HTTPS application URL."
  }
}

run "invalid_suffix" {
  command = plan
  variables {
    name_suffix = "BAD!"
  }
  expect_failures = [var.name_suffix]
}

run "blank_title" {
  command = plan
  variables {
    board_title = "   "
  }
  expect_failures = [var.board_title]
}

run "invalid_container" {
  command = plan
  variables {
    container_name = "bad--container"
  }
  expect_failures = [var.container_name]
}
