# REST API (v1), not HTTP API (v2): API keys and usage plans exist only in v1 (section
# 30.1). The key is a spending guard against scanners, not authentication.
resource "aws_api_gateway_rest_api" "complaints" {
  name = "complaints-api"
}

resource "aws_api_gateway_resource" "complaints" {
  rest_api_id = aws_api_gateway_rest_api.complaints.id
  parent_id   = aws_api_gateway_rest_api.complaints.root_resource_id
  path_part   = "complaints"
}

resource "aws_api_gateway_resource" "complaint" {
  rest_api_id = aws_api_gateway_rest_api.complaints.id
  parent_id   = aws_api_gateway_resource.complaints.id
  path_part   = "{complaint_id}"
}

locals {
  routes = {
    post = { resource_id = aws_api_gateway_resource.complaints.id, method = "POST" }
    get  = { resource_id = aws_api_gateway_resource.complaint.id, method = "GET" }
  }
}

resource "aws_api_gateway_method" "route" {
  for_each = local.routes

  rest_api_id   = aws_api_gateway_rest_api.complaints.id
  resource_id   = each.value.resource_id
  http_method   = each.value.method
  authorization = "NONE"

  # Both routes: a GET still invokes a Lambda and reads DynamoDB, so it costs money too.
  api_key_required = true
}

resource "aws_api_gateway_integration" "route" {
  for_each = local.routes

  rest_api_id             = aws_api_gateway_rest_api.complaints.id
  resource_id             = each.value.resource_id
  http_method             = aws_api_gateway_method.route[each.key].http_method
  type                    = "AWS_PROXY" # pass the raw request through; handler() parses it
  integration_http_method = "POST"      # Lambda is always invoked with POST
  uri                     = aws_lambda_function.api.invoke_arn
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.complaints.execution_arn}/*/*"
}

# A REST API needs an explicit deployment and stage (v2 does not). Redeploy whenever a
# route changes, or the stage keeps serving the old configuration.
resource "aws_api_gateway_deployment" "complaints" {
  rest_api_id = aws_api_gateway_rest_api.complaints.id

  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_resource.complaints,
      aws_api_gateway_resource.complaint,
      aws_api_gateway_method.route,
      aws_api_gateway_integration.route,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  rest_api_id   = aws_api_gateway_rest_api.complaints.id
  deployment_id = aws_api_gateway_deployment.complaints.id
  stage_name    = "prod"
}

# Sized for blast radius, not traffic (section 31): a public endpoint gets found by
# scanners within hours, and this caps the worst case at a rounding error.
resource "aws_api_gateway_usage_plan" "complaints" {
  name = "complaints-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.complaints.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }

  throttle_settings {
    rate_limit  = 5
    burst_limit = 10
  }

  quota_settings {
    limit  = 1000
    period = "DAY"
  }
}

resource "aws_api_gateway_api_key" "complaints" {
  name = "complaints-key"
}

resource "aws_api_gateway_usage_plan_key" "complaints" {
  key_id        = aws_api_gateway_api_key.complaints.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.complaints.id
}
