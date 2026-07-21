data "aws_availability_zones" "available" {
    state = "available"
}

# Amazon Linux 2023 AMI (operating system image for EC2)
data "aws_ami" "amazon_linux" {
    most_recent = true
    owners = ["amazon"]

    filter {
        name   = "name"
        values = ["al2023-ami-*-x86_64"]
    }
}

# VPC
resource "aws_vpc" "main" {
    cidr_block = var.vpc_cidr
    enable_dns_hostnames = true 
    enable_dns_support = true

    tags = {
        Name = "${var.project_name}-vpc"
        Environment = var.environment
    }
}

# Internet gateway -> VPC to public Internet
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

    tags = {
        Name = "${var.project_name}-igw"
    }
}

# Public subnet -> EC2 instances here get a public IP automatically
resource "aws_subnet" "public" {
    vpc_id = aws_vpc.main.id
  cidr_block = var.public_subnet_cidr
    availability_zone = data.aws_availability_zones.available.names[0]
    map_public_ip_on_launch = true 

    tags = {
        Name = "${var.project_name}-public-subnet"
    }
}

# Private subnets -> RDS 
resource "aws_subnet" "private" {
    count = 2
    vpc_id = aws_vpc.main.id
    cidr_block = var.private_subnet_cidrs[count.index]
    availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.project_name}-private-subnet-${count.index + 1}"
  }
}

# Route Table 
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
    
    route { 
        cidr_block = "0.0.0.0/0"
        gateway_id = aws_internet_gateway.main.id
    }

    tags = {
        Name = "${var.project_name}-public-rt"
    }
}

resource "aws_route_table_association" "public" {
    subnet_id = aws_subnet.public.id
    route_table_id = aws_route_table.public.id
}

# Security groups
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2-sg"
  description = "Security group for the EC2 app instance"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "App services (auth, inventory, trade)"
    from_port   = 8001
    to_port     = 8003
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Prometheus"
    from_port = 9090
    to_port = 9090
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Grafana"
    from_port = 3000
    to_port = 3000
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Locust"
    from_port = 8089
    to_port = 8089
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ec2-sg"
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "Security group for the PostgreSQL database"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from EC2"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-rds-sg"
  }
}

# IAM Role 
# The "assume role policy" — says "EC2 service is allowed to use this role"
resource "aws_iam_role" "ec2_role" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ec2-role"
  }
}

# Attach AWS-managed policy for ECR read access
resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Instance profile — the wrapper that lets you attach a role to an EC2 instance
resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# EC2 instance

resource "aws_instance" "app" {
  ami                    = data.aws_ami.amazon_linux.id  # latest Amazon Linux 2023
  instance_type          = var.ec2_instance_type          # t2.micro (free tier)
  subnet_id              = aws_subnet.public.id           # put in public subnet
  vpc_security_group_ids = [aws_security_group.ec2.id]   # attach our security group
  key_name               = var.ec2_key_pair_name          # SSH key pair
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  user_data = <<-EOF
    #!/bin/bash
    set -e

    yum update -y

    yum install -y docker
    systemctl start docker
    systemctl enable docker

    usermod -aG docker ec2-user

    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    # Create app directory
    mkdir -p /home/ec2-user/app
    chown ec2-user:ec2-user /home/ec2-user/app

    echo "Bootstrap complete" > /var/log/user-data-complete.log
  EOF

  root_block_device {
    volume_size = 30          # GB of storage
    volume_type = "gp3"       # general purpose SSD
    encrypted   = true
  }

  tags = {
    Name        = "${var.project_name}-ec2"
    Environment = var.environment
  }
}

# RDS Subnet group
resource "aws_db_subnet_group" "main" {
    name = "${var.project_name}-db-subnet-group"
    subnet_ids = aws_subnet.private[*].id # [*] 

    tags = {
        Name = "${var.project_name}-db-subnet-group"
    }
}

# RDS PostgreSQL Instance
resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-postgres"

  engine = "postgres"
  engine_version = "14.21"
  instance_class = "db.t3.micro"   

  allocated_storage = 20 # GB
  max_allocated_storage = 100       # autoscaling ceiling
  storage_type = "gp2"
  storage_encrypted = true

  db_name = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  multi_az = false
  publicly_accessible = false   
  skip_final_snapshot = true       # in production, set to false   

  backup_retention_period = 0     

  tags = {
    Name = "${var.project_name}-postgres"
    Environment = var.environment
  }
}