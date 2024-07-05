variable "project_name" {
  type        = string
  description = "The name of the project"
}

variable "environment" {
  type        = string
  description = "The environment (e.g., dev, prod)"
}

variable "member_id" {
  type = string
}

variable "member_pin" {
  type = string
}

variable "admin_password" {
  type = string
}

variable "mailchimp_api_key" {
  type = string
}
