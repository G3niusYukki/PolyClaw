provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "polyclaw"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
