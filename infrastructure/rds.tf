# RDS Postgres for PolyClaw
# Multi-AZ disabled for MVP; enable by setting multi_az = true

resource "aws_db_subnet_group" "polyclaw" {
  name       = "polyclaw-db-subnet-group"
  subnet_ids = length(var.private_subnet_ids) > 0 ? var.private_subnet_ids : aws_subnet.polyclaw_private[*].id

  tags = {
    Name = "polyclaw-db-subnet-group"
  }
}

resource "aws_security_group" "polyclaw_rds" {
  name        = "polyclaw-rds-sg"
  description = "Security group for PolyClaw RDS instance"
  vpc_id      = length(var.vpc_id) > 0 ? var.vpc_id : aws_vpc.polyclaw[0].id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
    description = "Postgres from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "polyclaw-rds-sg"
  }
}

resource "aws_db_parameter_group" "polyclaw" {
  name        = "polyclaw-db-param-group"
  family      = "postgres16"
  description = "Parameter group for PolyClaw Postgres 16"

  parameter {
    name  = "max_connections"
    value = "100"
  }

  parameter {
    name  = "shared_buffers"
    value = "128MB"
  }

  parameter {
    name  = "effective_cache_size"
    value = "256MB"
  }

  parameter {
    name  = "maintenance_work_mem"
    value = "128MB"
  }

  parameter {
    name  = "checkpoint_completion_target"
    value = "0.9"
  }

  parameter {
    name  = "wal_buffers"
    value = "4MB"
  }

  parameter {
    name  = "default_statistics_target"
    value = "100"
  }

  parameter {
    name  = "random_page_cost"
    value = "1.1"
  }

  parameter {
    name  = "effective_io_concurrency"
    value = "200"
  }

  parameter {
    name  = "work_mem"
    value = "2MB"
  }

  parameter {
    name  = "min_wal_size"
    value = "1GB"
  }

  parameter {
    name  = "max_wal_size"
    value = "4GB"
  }

  tags = {
    Name = "polyclaw-db-param-group"
  }
}

resource "aws_db_instance" "polyclaw" {
  identifier     = "polyclaw-db"
  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.db_instance_class

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password != "" ? var.db_password : sensitive("REPLACE_WITH_SECRETS_MANAGER_REF")

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 3
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.polyclaw.name
  vpc_security_group_ids = [aws_security_group.polyclaw_rds.id]

  parameter_group_name = aws_db_parameter_group.polyclaw.name

  multi_az            = false
  publicly_accessible = false
  skip_final_snapshot = true
  deletion_protection = false # Set to true in prod

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:00-mon:05:00"

  performance_insights_enabled   = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = {
    Name = "polyclaw-db"
  }
}

# VPC resources (created if not provided)
resource "aws_vpc" "polyclaw" {
  count = length(var.vpc_id) > 0 ? 0 : 1

  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "polyclaw-vpc"
  }
}

resource "aws_subnet" "polyclaw_private" {
  count = length(var.vpc_id) > 0 || length(var.private_subnet_ids) > 0 ? 0 : 2

  vpc_id            = aws_vpc.polyclaw[0].id
  cidr_block        = count.index == 0 ? "10.0.1.0/24" : "10.0.2.0/24"
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "polyclaw-private-subnet-${count.index + 1}"
  }
}

resource "aws_internet_gateway" "polyclaw" {
  count  = length(var.vpc_id) > 0 ? 0 : 1
  vpc_id = aws_vpc.polyclaw[0].id

  tags = {
    Name = "polyclaw-igw"
  }
}

resource "aws_route_table" "polyclaw_private" {
  count  = length(var.vpc_id) > 0 || length(var.private_subnet_ids) > 0 ? 0 : 1
  vpc_id = aws_vpc.polyclaw[0].id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.polyclaw[0].id
  }

  tags = {
    Name = "polyclaw-private-rt"
  }
}

resource "aws_eip" "polyclaw_nat" {
  count  = length(var.vpc_id) > 0 || length(var.private_subnet_ids) > 0 ? 0 : 1
  domain = "vpc"

  tags = {
    Name = "polyclaw-nat-eip"
  }
}

resource "aws_nat_gateway" "polyclaw" {
  count = length(var.vpc_id) > 0 || length(var.private_subnet_ids) > 0 ? 0 : 1

  allocation_id = aws_eip.polyclaw_nat[0].id
  subnet_id     = aws_subnet.polyclaw_public[0].id

  tags = {
    Name = "polyclaw-nat"
  }

  depends_on = [aws_internet_gateway.polyclaw]
}

resource "aws_subnet" "polyclaw_public" {
  count = length(var.vpc_id) > 0 || length(var.private_subnet_ids) > 0 ? 0 : 1

  vpc_id            = aws_vpc.polyclaw[0].id
  cidr_block        = "10.0.0.0/24"
  availability_zone = var.availability_zones[0]

  tags = {
    Name = "polyclaw-public-subnet"
  }
}

resource "aws_route_table_association" "polyclaw_private" {
  count = length(var.private_subnet_ids) > 0 ? 0 : 2

  subnet_id      = aws_subnet.polyclaw_private[count.index].id
  route_table_id = aws_route_table.polyclaw_private[0].id
}

resource "aws_route_table_association" "polyclaw_public" {
  count = length(var.vpc_id) > 0 || length(var.private_subnet_ids) > 0 ? 0 : 1

  subnet_id      = aws_subnet.polyclaw_public[0].id
  route_table_id = aws_vpc.polyclaw[0].default_route_table_id
}
