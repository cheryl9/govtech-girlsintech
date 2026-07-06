# Outputs print important values after terraform apply completes
# Like return values from a function

output "ec2_public_ip" {
  description = "Public IP of the EC2 instance — SSH into this"
  value = aws_instance.app.public_ip
}

output "ec2_public_dns" {
  description = "Public DNS of EC2"
  value = aws_instance.app.public_dns
}

output "rds_endpoint" {
  description = "RDS connection endpoint — use this as DB_HOST in your app"
  value = aws_db_instance.postgres.endpoint
  sensitive = true
}

output "rds_port" {
  description = "RDS port"
  value = aws_db_instance.postgres.port
}

output "ssh_command" {
  description = "Copy-paste SSH command to connect to EC2"
  value = "ssh -i ~/.ssh/devops-key.pem ec2-user@${aws_instance.app.public_ip}"
}