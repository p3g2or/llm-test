variable "project_name" {
  type        = string
  description = "Short application prefix used for resource naming."
  default     = "fieldnotes"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,11}$", var.project_name))
    error_message = "Use 3-12 lowercase letters or digits, starting with a letter."
  }
}

variable "name_suffix" {
  type        = string
  description = "Unique suffix for globally named Azure resources."
  validation {
    condition     = can(regex("^[a-z0-9]{4,8}$", var.name_suffix))
    error_message = "Use 4-8 lowercase letters or digits."
  }
}

variable "location" {
  type        = string
  description = "Azure region for dev resources."
  default     = "westeurope"
}

variable "board_title" {
  type        = string
  description = "Notebook title displayed by the frontend through /api/config."
  default     = "Field Notes"
  validation {
    condition     = length(trimspace(var.board_title)) > 0 && length(var.board_title) <= 80
    error_message = "Board title must contain 1-80 characters."
  }
}

variable "container_name" {
  type        = string
  description = "Private blob container used by the note repository."
  default     = "notes"
  validation {
    condition = (
      can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.container_name)) &&
      !strcontains(var.container_name, "--")
    )
    error_message = "Use 3-63 lowercase letters, digits or single interior hyphens."
  }
}
