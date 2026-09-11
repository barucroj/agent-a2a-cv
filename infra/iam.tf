data "aws_caller_identity" "current" {}

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
