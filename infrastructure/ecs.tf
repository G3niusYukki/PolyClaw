# ---------------------------------------------------------------------------
# ECS Cluster and Task Definitions for PolyClaw
# Fargate launch type with VPC networking
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "polyclaw" {
  name = "${var.environment}-polyclaw-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

resource "aws_ecs_cluster_capacity_providers" "polyclaw" {
  cluster_name = aws_ecs_cluster.polyclaw.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# ---------------------------------------------------------------------------
# Task Definitions
# Each service runs as a separate ECS task with 0.5 vCPU / 1GB memory (MVP)
# ---------------------------------------------------------------------------

# Ingestion Service
resource "aws_ecs_task_definition" "ingestion_service" {
  family                   = "${var.environment}-polyclaw-ingestion"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"   # 0.5 vCPU
  memory                   = "1024"  # 1 GB

  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn      = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "ingestion"
      image     = "${aws_ecr_repository.polyclaw.repository_url}:ingestion-latest"
      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "MARKET_SOURCE", value = "polymarket" },
        { name = "DATABASE_URL", value = var.database_url },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.polyclaw_db.arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ingestion_service.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ingestion"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

# Strategy Engine Service
resource "aws_ecs_task_definition" "strategy_engine" {
  family                   = "${var.environment}-polyclaw-strategy"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn      = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "strategy-engine"
      image     = "${aws_ecr_repository.polyclaw.repository_url}:strategy-latest"
      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "DATABASE_URL", value = var.database_url },
        { name = "MIN_CONFIDENCE", value = "0.62" },
        { name = "MIN_EDGE_BPS", value = "700" },
        { name = "EXECUTION_MODE", value = "paper" },
        { name = "SHADOW_MODE_ENABLED", value = "true" },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.polyclaw_db.arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.strategy_engine.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "strategy"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      dependencies = [
        { targetContainer = "ingestion", condition = "HEALTHY" }
      ]
    }
  ])

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

# Execution Service
resource "aws_ecs_task_definition" "execution_service" {
  family                   = "${var.environment}-polyclaw-execution"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn      = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "execution"
      image     = "${aws_ecr_repository.polyclaw.repository_url}:execution-latest"
      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "DATABASE_URL", value = var.database_url },
        { name = "EXECUTION_MODE", value = "paper" },
        { name = "LIVE_TRADING_ENABLED", value = "false" },
        { name = "SHADOW_MODE_ENABLED", value = "true" },
        { name = "SHADOW_STAGE", value = "0" },
        { name = "MAX_DAILY_LOSS_USD", value = "200" },
        { name = "REQUIRE_APPROVAL", value = "true" },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.polyclaw_db.arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.execution_service.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "execution"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

# Monitor Service
resource "aws_ecs_task_definition" "monitor_service" {
  family                   = "${var.environment}-polyclaw-monitor"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn      = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "monitor"
      image     = "${aws_ecr_repository.polyclaw.repository_url}:monitor-latest"
      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "DATABASE_URL", value = var.database_url },
        { name = "SHADOW_MODE_ENABLED", value = "true" },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.polyclaw_db.arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.monitor_service.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "monitor"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

# ---------------------------------------------------------------------------
# CloudWatch Log Groups
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ingestion_service" {
  name              = "/ecs/${var.environment}/polyclaw/ingestion"
  retention_in_days = 14
  tags = {
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "strategy_engine" {
  name              = "/ecs/${var.environment}/polyclaw/strategy-engine"
  retention_in_days = 14
  tags = {
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "execution_service" {
  name              = "/ecs/${var.environment}/polyclaw/execution"
  retention_in_days = 14
  tags = {
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "monitor_service" {
  name              = "/ecs/${var.environment}/polyclaw/monitor"
  retention_in_days = 14
  tags = {
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# Security Group — allows internal ECS communication
# ---------------------------------------------------------------------------

resource "aws_security_group" "ecs_services" {
  name        = "${var.environment}-polyclaw-ecs-sg"
  description = "Security group for PolyClaw ECS services"
  vpc_id      = var.vpc_id

  ingress = [
    {
      description = "Internal HTTP traffic"
      from_port   = 8080
      to_port     = 8080
      protocol    = "tcp"
      cidr_blocks = ["10.0.0.0/16"]  # VPC CIDR
    }
  ]

  egress = [
    {
      description = "Allow all outbound"
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
    }
  ]

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

# ---------------------------------------------------------------------------
# ECR Repository
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "polyclaw" {
  name                 = "polyclaw"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = {
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# Secrets Manager Secret (placeholder — password injected via variable)
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "polyclaw_db" {
  name        = "${var.environment}/polyclaw/database-url"
  description = "PolyClaw database connection string"

  recovery_window_in_days = 7
  tags = {
    Environment = var.environment
  }
}
