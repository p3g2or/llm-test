variable "name" {
  type        = string
  description = "Resource group name."
  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]{1,90}$", var.name))
    error_message = "Use 1-90 letters, digits, underscores or hyphens."
  }
}

variable "location" {
  type        = string
  description = "Azure region."
  validation {
    condition     = length(trimspace(var.location)) > 0
    error_message = "Location must not be empty."
  }
}

variable "tags" {
  type        = map(string)
  description = "Resource tags."
  default     = {}
}
