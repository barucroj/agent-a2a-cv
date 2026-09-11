variable "aws_region" {
  description = "Region de AWS donde se despliega la infraestructura."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Perfil local de AWS CLI a usar (credenciales configuradas con 'aws configure --profile agent-cv')."
  type        = string
  default     = "agent-cv"
}

variable "service_name" {
  description = "Nombre base para los recursos del servicio."
  type        = string
  default     = "agent-cv"
}

variable "image_tag" {
  description = "Tag de la imagen en ECR a resolver (a su digest real) en cada plan/apply."
  type        = string
  default     = "latest"
}
