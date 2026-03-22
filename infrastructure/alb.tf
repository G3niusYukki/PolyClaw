# ---------------------------------------------------------------------------
# Application Load Balancer for PolyClaw ECS Services
# HTTP listener on port 80 with target groups per service
# ---------------------------------------------------------------------------

resource "aws_lb" "polyclaw" {
  name               = "${var.environment}-polyclaw-alb"
  internal           = false # Public-facing for MVP; use internal for production
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false # Set true in production

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

# ---------------------------------------------------------------------------
# Security Group for ALB
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb_sg" {
  name        = "${var.environment}-polyclaw-alb-sg"
  description = "Security group for PolyClaw ALB"
  vpc_id      = var.vpc_id

  ingress {
    description = "Allow HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Allow HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = var.environment
    Project     = "polyclaw"
  }
}

# ---------------------------------------------------------------------------
# Target Groups
# One per ECS service (using HTTP health checks on /health)
# ---------------------------------------------------------------------------

resource "aws_lb_target_group" "ingestion" {
  name     = "${var.environment}-polyclaw-ingestion-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  deregistration_delay = 30
  target_type          = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "strategy_engine" {
  name     = "${var.environment}-polyclaw-strategy-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  deregistration_delay = 30
  target_type          = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "execution" {
  name     = "${var.environment}-polyclaw-execution-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  deregistration_delay = 30
  target_type          = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "monitor" {
  name     = "${var.environment}-polyclaw-monitor-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  deregistration_delay = 30
  target_type          = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# ECS Service Attachments to Target Groups
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "ingestion" {
  name            = "${var.environment}-polyclaw-ingestion"
  cluster         = aws_ecs_cluster.polyclaw.name
  task_definition = aws_ecs_task_definition.ingestion_service.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_services.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ingestion.arn
    container_name   = "ingestion"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.polyclaw_http]

  tags = {
    Environment = var.environment
  }
}

resource "aws_ecs_service" "strategy_engine" {
  name            = "${var.environment}-polyclaw-strategy"
  cluster         = aws_ecs_cluster.polyclaw.name
  task_definition = aws_ecs_task_definition.strategy_engine.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_services.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.strategy_engine.arn
    container_name   = "strategy-engine"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.polyclaw_http]

  tags = {
    Environment = var.environment
  }
}

resource "aws_ecs_service" "execution" {
  name            = "${var.environment}-polyclaw-execution"
  cluster         = aws_ecs_cluster.polyclaw.name
  task_definition = aws_ecs_task_definition.execution_service.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_services.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.execution.arn
    container_name   = "execution"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.polyclaw_http]

  tags = {
    Environment = var.environment
  }
}

resource "aws_ecs_service" "monitor" {
  name            = "${var.environment}-polyclaw-monitor"
  cluster         = aws_ecs_cluster.polyclaw.name
  task_definition = aws_ecs_task_definition.monitor_service.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_services.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.monitor.arn
    container_name   = "monitor"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.polyclaw_http]

  tags = {
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# HTTP Listener (port 80) — routes to all target groups by path pattern
# ---------------------------------------------------------------------------

resource "aws_lb_listener" "polyclaw_http" {
  load_balancer_arn = aws_lb.polyclaw.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ingestion.arn
  }
}

# Path-based routing rules
resource "aws_lb_listener_rule" "strategy_routing" {
  listener_arn = aws_lb_listener.polyclaw_http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.strategy_engine.arn
  }

  condition {
    path_pattern {
      values = ["/strategy/*", "/api/strategy/*"]
    }
  }
}

resource "aws_lb_listener_rule" "execution_routing" {
  listener_arn = aws_lb_listener.polyclaw_http.arn
  priority     = 101

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.execution.arn
  }

  condition {
    path_pattern {
      values = ["/execute*", "/api/execute/*", "/decisions/*", "/positions/*"]
    }
  }
}

resource "aws_lb_listener_rule" "monitor_routing" {
  listener_arn = aws_lb_listener.polyclaw_http.arn
  priority     = 102

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.monitor.arn
  }

  condition {
    path_pattern {
      values = ["/shadow/*", "/api/shadow/*", "/monitor/*"]
    }
  }
}
