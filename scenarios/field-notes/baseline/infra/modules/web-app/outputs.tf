output "name" {
  description = "Web app deployment target."
  value       = azurerm_linux_web_app.this.name
}

output "url" {
  description = "Application HTTPS URL."
  value       = "https://${azurerm_linux_web_app.this.default_hostname}"
}

output "principal_id" {
  description = "Managed identity used for storage access."
  value       = azurerm_linux_web_app.this.identity[0].principal_id
}
