data "aws_caller_identity" "current" {}

# Claude Haiku 4.5 en us-east-1 NO soporta invocacion In-Region via
# bedrock-runtime (verificado en la ficha oficial del modelo): hace falta un
# inference profile de cross-region. Se usa el geografico "us." (no el
# global) para mantener los datos dentro de EEUU. Los destinos de ese
# profile desde us-east-1 son us-east-1/us-east-2/us-west-2 (tambien
# verificado contra la doc oficial), de ahi las 3 regiones de abajo.
locals {
  bedrock_model_id              = "anthropic.claude-haiku-4-5-20251001-v1:0"
  bedrock_inference_profile_id  = "us.${local.bedrock_model_id}"
  bedrock_geo_us_regions        = ["us-east-1", "us-east-2", "us-west-2"]
  bedrock_inference_profile_arn = "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${local.bedrock_inference_profile_id}"

  # El segundo statement es requisito documentado de AWS para cross-region
  # inference: el permiso sobre el inference profile por si solo no basta,
  # tambien hace falta permiso sobre los foundation-model ARN de las regiones
  # destino (sin account id en ese ARN), acotado mediante condicion al
  # profile de arriba. Se reutiliza tal cual para el Task Role y para el
  # usuario de despliegue local (pruebas del paso 8).
  #
  # bedrock:InvokeModelWithResponseStream (paso 13, streaming): es la accion
  # que usa la Converse Stream API, distinta de InvokeModel (Converse no
  # streaming). Sin ella, ConverseStream falla en runtime con
  # AccessDeniedException aunque InvokeModel funcione -- se detecto asi en
  # produccion tras el primer intento de despliegue de streaming.
  bedrock_invoke_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeInferenceProfile"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = local.bedrock_inference_profile_arn
      },
      {
        Sid    = "InvokeUnderlyingFoundationModel"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          for region in local.bedrock_geo_us_regions :
          "arn:aws:bedrock:${region}::foundation-model/${local.bedrock_model_id}"
        ]
        Condition = {
          StringEquals = {
            "bedrock:InferenceProfileArn" = local.bedrock_inference_profile_arn
          }
        }
      }
    ]
  })
}

# Execution Role: lo usa ECS para hacer pull de la imagen en ECR y escribir logs.
# (Antes era el Access Role de App Runner; migrado a ECS Express Mode.)
resource "aws_iam_role" "apprunner_ecr_access" {
  name = "${var.service_name}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  role       = aws_iam_role.apprunner_ecr_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Task Role: lo asume el CODIGO de la app corriendo dentro del contenedor de ECS.
# (Antes era el Instance Role de App Runner.)
resource "aws_iam_role" "apprunner_instance" {
  name = "${var.service_name}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Lectura de secretos acotada al prefijo del proyecto (no "*"). La app todavia no
# llama a Secrets Manager: queda listo para el paso 9.
resource "aws_iam_role_policy" "apprunner_instance_secrets" {
  name = "${var.service_name}-secrets-read"
  role = aws_iam_role.apprunner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.service_name}/*"
    }]
  })
}

# Permiso de invocacion de Bedrock (paso 8) para el Task Role, acotado al
# inference profile y modelo especificos (no bedrock:* ni foundation-model/*).
resource "aws_iam_role_policy" "apprunner_instance_bedrock" {
  name   = "${var.service_name}-bedrock-invoke"
  role   = aws_iam_role.apprunner_instance.id
  policy = local.bedrock_invoke_policy_json
}

# Mismo permiso, mismo alcance exacto, para el usuario de despliegue local
# (agent-cv-deploy, no gestionado por Terraform) — unicamente para poder
# probar el flujo real de Bedrock desde fuera de ECS antes de desplegar.
# NOTA: a partir de este recurso, Terraform gestiona una policy sobre un
# usuario que sigue existiendo fuera de Terraform (se creo a mano). Es una
# mezcla aceptable (se puede adjuntar una policy a un usuario por nombre sin
# gestionar el usuario completo), pero si ese usuario se borra o renombra a
# mano desde la consola, el state de Terraform queda desincronizado
# unicamente para este recurso.
resource "aws_iam_user_policy" "deploy_user_bedrock" {
  name   = "${var.service_name}-bedrock-invoke"
  user   = "agent-cv-deploy"
  policy = local.bedrock_invoke_policy_json
}

# Infrastructure Role: lo usa ECS Express Mode para aprovisionar el ALB, target
# groups, auto scaling y networking por nosotros. No existia en la version App Runner.
resource "aws_iam_role" "ecs_express_infrastructure" {
  name = "${var.service_name}-ecs-express-infrastructure"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowAccessInfrastructureForECSExpressServices"
      Effect    = "Allow"
      Principal = { Service = "ecs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_express_infrastructure" {
  role       = aws_iam_role.ecs_express_infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}
