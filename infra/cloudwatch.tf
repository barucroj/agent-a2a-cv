# Log group propio de aplicacion (distinto de los que App Runner crea solo para
# stdout/stderr del contenedor). Queda listo para logging estructurado (paso 10).
resource "aws_cloudwatch_log_group" "agent_cv_app" {
  name              = "/${var.service_name}/app"
  retention_in_days = 30
}
