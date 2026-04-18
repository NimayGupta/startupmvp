variable "aws_region" {
  default = "us-east-1"
}

variable "app_name" {
  default = "discount-optimizer"
}

variable "environment" {
  description = "staging or production"
  type        = string
}

variable "aws_account_id" {
  description = "12-digit AWS account ID"
  type        = string
}

variable "db_password" {
  description = "RDS master password — store in Secrets Manager, pass via TF_VAR"
  type        = string
  sensitive   = true
}

variable "vpc_cidr" {
  default = "10.0.0.0/16"
}

variable "engine_cpu" {
  default = 512
}

variable "engine_memory" {
  default = 1024
}

variable "remix_cpu" {
  default = 512
}

variable "remix_memory" {
  default = 1024
}

variable "worker_cpu" {
  default = 512
}

variable "worker_memory" {
  default = 1024
}
