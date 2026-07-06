terraform {
    required_version = ">= 1.0"

    required_providers {
        aws = {
            source = "hashicorp/aws"
            version = "~> 5.0"
        }
    }

    backend "s3" {
        bucket = "cheryl-terraform-state-2026"
        key = "devops-project/terraform.tfstate"
        region = "ap-southeast-1"
        use_lockfile = true
        encrypt = true
    }
}

provider "aws" {
    region = var.aws_region
}