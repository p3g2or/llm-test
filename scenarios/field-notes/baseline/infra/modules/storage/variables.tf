variable "name" {
  type        = string
  description = "Globally unique storage account name."
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.name))
    error_message = "Storage names must contain 3-24 lowercase letters or digits."
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

variable "container_name" {
  type        = string
  description = "Private note container."
  default     = "notes"
  validation {
    condition = (
      can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.container_name)) &&
      !strcontains(var.container_name, "--")
    )
    error_message = "Use 3-63 lowercase letters, digits or single interior hyphens."
  }
}

variable "tags" {
  type        = map(string)
  description = "Resource tags."
  default     = {}
}
