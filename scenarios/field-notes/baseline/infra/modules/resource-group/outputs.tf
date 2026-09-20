output "name" {
  description = "Resource group name."
  value       = azurerm_resource_group.this.name
}

output "location" {
  description = "Resource group region."
  value       = azurerm_resource_group.this.location
}
