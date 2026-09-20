output "resource_group_name" {
  description = "Resource group used by release deployment."
  value       = module.resource_group.name
}

output "web_app_name" {
  description = "App Service deployment target."
  value       = module.web_app.name
}

output "app_url" {
  description = "Application URL after deploying the release archive."
  value       = module.web_app.url
}

output "runtime_settings" {
  description = "Non-secret settings supplied to the backend."
  value       = local.runtime_settings
}
