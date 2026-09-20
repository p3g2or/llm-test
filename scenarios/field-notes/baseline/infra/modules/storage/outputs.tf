output "account_url" {
  description = "Blob endpoint used by the backend."
  value       = azurerm_storage_account.this.primary_blob_endpoint
}

output "container_name" {
  description = "Private note container name."
  value       = azurerm_storage_container.notes.name
}

output "container_resource_id" {
  description = "ARM scope for assigning container-level data access."
  value       = azurerm_storage_container.notes.id
}
