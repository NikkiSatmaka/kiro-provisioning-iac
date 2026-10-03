# =============================================================================
# Lambda + Function URL + least-privilege IAM role
# =============================================================================
#
# One Python 3.12 Lambda, fronted by exactly ONE Function URL, serves the whole
# service: GET returns the inline claim page, POST runs the claim pipeline
# (design: "Function URL and request routing"). There is deliberately NO API
# Gateway and NO WAF (Requirements 9.1, 9.3). The deployment package is just the
# handler plus the inlined index.html — boto3 is already in the Lambda runtime.
# =============================================================================

# ---------------------------------------------------------------------------
# Deployment package: zip the handler and the claim page so index.html lands at
# the zip root as a sibling of claim_handler.py (design: served inline at
# package time). source_code_hash wires redeploys to content changes.
# ---------------------------------------------------------------------------
data "archive_file" "claim_handler" {
  type        = "zip"
  output_path = "${path.module}/build/claim_handler.zip"

  source {
    content  = file("${path.module}/../lambda/claim_handler.py")
    filename = "claim_handler.py"
  }

  source {
    content  = file("${path.module}/../frontend/index.html")
    filename = "index.html"
  }
}

# ---------------------------------------------------------------------------
# Execution role (least privilege, Requirement 10.3)
# ---------------------------------------------------------------------------
# The role trusts only the Lambda service, attaches the AWS-managed basic
# execution policy for CloudWatch Logs, and grants EXACTLY the five DynamoDB
# actions the handler issues — scoped to the single claim table ARN and nothing
# else. No subscription/ or backend/ resource is referenced.
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "claim_handler" {
  name               = "${var.table_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

# CloudWatch Logs via the AWS-managed basic execution role.
resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.claim_handler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# The only data-plane permissions the handler needs: Scan (pick_available),
# UpdateItem (per-IP counter + the transact Update), TransactWriteItems (the
# claim), GetItem (reclaim + success readback), and PutItem (seed/lock put).
# Resource is the one table ARN only (local.claim_table_arn).
data "aws_iam_policy_document" "claim_table_access" {
  statement {
    sid    = "ClaimTableLeastPrivilege"
    effect = "Allow"

    actions = [
      "dynamodb:Scan",
      "dynamodb:UpdateItem",
      "dynamodb:TransactWriteItems",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
    ]

    resources = [local.claim_table_arn]
  }
}

resource "aws_iam_role_policy" "claim_table_access" {
  name   = "${var.table_name}-table-access"
  role   = aws_iam_role.claim_handler.id
  policy = data.aws_iam_policy_document.claim_table_access.json
}

# ---------------------------------------------------------------------------
# The function
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "claim_handler" {
  function_name = var.table_name
  role          = aws_iam_role.claim_handler.arn

  runtime = "python3.12"
  handler = "claim_handler.handler"

  filename         = data.archive_file.claim_handler.output_path
  source_code_hash = data.archive_file.claim_handler.output_base64sha256

  memory_size = 128
  timeout     = 10

  environment {
    variables = {
      TABLE_NAME     = local.claim_table_name
      WORKSHOP_CODE  = var.workshop_code
      ALLOWED_ORIGIN = var.allowed_origin
      # Lambda env values must be strings; the handler coerces back to int.
      RETRY_BOUND = tostring(var.retry_bound)
      PER_IP_CAP  = tostring(var.per_ip_cap)
    }
  }

  # Logs are written via the basic-execution policy; make the function depend on
  # the attachment so the role can write from the first invocation.
  depends_on = [aws_iam_role_policy_attachment.basic_execution]
}

# ---------------------------------------------------------------------------
# The single public Function URL (authorization NONE; gated in the handler by
# the workshop code + per-IP cap, Requirement 12). CORS allow_origins is the
# configured origin, falling back to "*" when allowed_origin is empty because
# the Function URL's own origin is only known post-apply (see variables.tf).
# ---------------------------------------------------------------------------
resource "aws_lambda_function_url" "claim_handler" {
  function_name      = aws_lambda_function.claim_handler.function_name
  authorization_type = "NONE"

  cors {
    allow_origins = [var.allowed_origin != "" ? var.allowed_origin : "*"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type"]
  }
}
