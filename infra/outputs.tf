output "ecs_service_ingress_paths" {
  description = "Endpoints publicos del servicio ECS Express Mode (access_type + endpoint). Formato esperado: https://<service>.ecs.<region>.on.aws"
  value       = aws_ecs_express_gateway_service.agent_cv.ingress_paths
}

output "ecr_repository_url" {
  description = "URL del repositorio ECR (para docker push)."
  value       = aws_ecr_repository.agent_cv.repository_url
}

output "ecs_task_role_arn" {
  description = "ARN del task role de ECS (antes instance role de App Runner)."
  value       = aws_iam_role.apprunner_instance.arn
}

output "app_log_group_name" {
  description = "Nombre del log group de aplicacion en CloudWatch."
  value       = aws_cloudwatch_log_group.agent_cv_app.name
}
