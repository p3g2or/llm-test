variable "name" {
  type        = string
  description = "Globally unique web app name."
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$", var.name))
    error_message = "Use 2-60 lowercase letters, digits or interior hyphens."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Parent resource group."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "app_settings" {
  type        = map(string)
  description = "Non-secret runtime settings."
  default     = {}
}

variable "tags" {
  type        = map(string)
  description = "Resource tags."
  default     = {}
}
