terraform {
 required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "5.9.0"
    }
  }
  cloud {
    organization = "Cataprato"

    workspaces {
      name = "cataprato-auth"
    }
  }
}
provider "aws" {
  region = "us-east-1"
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_credentials_validation = true
  skip_requesting_account_id  = false
}


data "aws_caller_identity" "current" {}

data "aws_organizations_organization" "this" {}


module "lambda_function" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "5.3.0"

  function_name          = "authorization"
  description            = "Cataprato lambda authorizer"
  handler                = "app.main.handler"
  runtime                = "python3.10"
  architectures          = ["x86_64"]
  publish                = true

   source_path            = [
                           {
                               path          = "${path.module}/dist/src"  
                            }
                            ]


  store_on_s3 = true
  s3_bucket   = module.s3_bucket.s3_bucket_id
  s3_prefix   = "lambda-builds/"

  artifacts_dir = "${path.root}/.terraform/lambda-builds/"

  layers = [
    module.lambda_layer_s3.lambda_layer_arn,
  ]

  role_path   = "/tf-managed/"
  policy_path = "/tf-managed/"

  allowed_triggers = {
    APIGatewayAny = {
      service    = "apigateway"
      source_arn = "${data.aws_apigatewayv2_api.cataprato_api.execution_arn}/*/*"
    }
  }


  create_lambda_function_url = true
  authorization_type         = "AWS_IAM"
  cors = {
    allow_credentials = true
    allow_origins     = ["*"]
    allow_methods     = ["*"]
    allow_headers     = ["date", "keep-alive"]
    expose_headers    = ["keep-alive", "date"]
    max_age           = 86400
  }
  invoke_mode = "RESPONSE_STREAM"

   attach_policy_statements = true
  policy_statements = {
    dynamodb = {
      effect    = "Allow",
      actions   = [
        "dynamodb:*"
],
      resources = ["${data.aws_dynamodb_table.users.arn}"]
    },
  }

  timeouts = {
    create = "20m"
    update = "20m"
    delete = "20m"
  }

   tags = {
    Deployment = "terraform"
  }
}

module "lambda_layer_s3" {
   source  = "terraform-aws-modules/lambda/aws"
  version = "5.3.0"

  create_layer = true

  layer_name          = "cataprato-auth-layer-s3"
  description         = "Pip layer"
  compatible_runtimes = ["python3.10"]

  create_package = true
  source_path = "dist"

  store_on_s3 = true
  s3_bucket   = module.s3_bucket.s3_bucket_id

tags = {
    Deployment = "terraform"
  }
}

module "s3_bucket" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "3.14.1"

  bucket_prefix = "cataprato-authorization-"
  force_destroy = true

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  versioning = {
    enabled = true
  }
}

data "aws_dynamodb_table" "users" {
  name = "Users"
}

data "aws_apigatewayv2_api" "cataprato_api" {
  api_id = one(data.aws_apigatewayv2_apis.cataprato.ids)
}
data "aws_apigatewayv2_apis" "cataprato"{
  protocol_type  = "HTTP"
}