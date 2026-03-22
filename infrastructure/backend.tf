terraform {
  required_version = ">= 1.3"

  backend "s3" {
    bucket = "polyclaw-terraform-state"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"
    encrypt = true
  }
}
