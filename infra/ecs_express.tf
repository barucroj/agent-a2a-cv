# Resuelve el tag al digest real y actual en cada plan/apply, para no
# depender de que "latest" siga apuntando al build que uno cree que apunta.
data "aws_ecr_image" "agent_cv" {
  repository_name = aws_ecr_repository.agent_cv.name
  image_tag       = var.image_tag
}

resource "aws_ecs_express_gateway_service" "agent_cv" {
  service_name            = var.service_name
  execution_role_arn      = aws_iam_role.apprunner_ecr_access.arn
  infrastructure_role_arn = aws_iam_role.ecs_express_infrastructure.arn
  task_role_arn           = aws_iam_role.apprunner_instance.arn
  health_check_path       = "/health"

  primary_container {
    image          = data.aws_ecr_image.agent_cv.image_uri
    container_port = 8000

    # Unica fuente de verdad para la region que usa boto3 al invocar Bedrock
    # (app/llm.py) -- debe coincidir con la region a la que iam.tf acota el
    # ARN del inference profile. Nota: cambios a este bloque `environment` en
    # este recurso tienen el bug conocido de propagacion in-place
    # (terraform-provider-aws#45792, documentado en el README) -- a
    # diferencia de PUBLIC_BASE_URL (que cambiaba en cada deploy), esta
    # variable practicamente no cambia, asi que el costo de un `-replace`
    # ocasional es aceptable aqui.
    environment {
      name  = "AWS_REGION"
      value = var.aws_region
    }

    aws_logs_configuration = [{
      log_group         = aws_cloudwatch_log_group.agent_cv_app.name
      log_stream_prefix = var.service_name
    }]
  }
}
