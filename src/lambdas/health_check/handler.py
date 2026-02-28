"""
Health Check Lambda Handler.

This Lambda function performs periodic health checks on core infrastructure
components (DynamoDB tables, SQS queues, and Lambda functions) and emits
metrics to CloudWatch.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.metrics import MetricUnit
import boto3

from .checks import (
    DynamoDBHealthChecker,
    SQSHealthChecker,
    LambdaHealthChecker,
    HealthStatus
)

# Initialize AWS Lambda Powertools
logger = Logger(service="health-check")
tracer = Tracer(service="health-check")
metrics = Metrics(namespace="AIGroceryApp", service="health-check")

# Initialize AWS clients
cloudwatch_client = boto3.client("cloudwatch")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "unknown")
DYNAMODB_TABLES = os.environ.get("DYNAMODB_TABLES", "")
SQS_QUEUES = os.environ.get("SQS_QUEUES", "")
LAMBDA_FUNCTIONS = os.environ.get("LAMBDA_FUNCTIONS", "")


@tracer.capture_method
def parse_resource_list(resource_string: str) -> list:
    """
    Parse comma-separated resource string into list.
    
    Args:
        resource_string: Comma-separated string of resources
        
    Returns:
        List of non-empty resource identifiers
    """
    if not resource_string:
        return []
    return [r.strip() for r in resource_string.split(",") if r.strip()]


@tracer.capture_method
def check_all_services() -> Dict[str, Any]:
    """
    Perform health checks on all configured services.
    
    Returns:
        Dictionary with health status for all services
    """
    logger.info(
        "Starting health check",
        extra={
            "environment": ENVIRONMENT,
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    
    # Parse resource lists
    dynamodb_tables = parse_resource_list(DYNAMODB_TABLES)
    sqs_queues = parse_resource_list(SQS_QUEUES)
    lambda_functions = parse_resource_list(LAMBDA_FUNCTIONS)
    
    # Initialize health checkers
    dynamodb_checker = DynamoDBHealthChecker()
    sqs_checker = SQSHealthChecker()
    lambda_checker = LambdaHealthChecker()
    
    # Perform checks
    logger.debug(
        "Checking resources",
        extra={
            "dynamodb_count": len(dynamodb_tables),
            "sqs_count": len(sqs_queues),
            "lambda_count": len(lambda_functions)
        }
    )
    
    dynamodb_health = dynamodb_checker.check_tables(dynamodb_tables)
    sqs_health = sqs_checker.check_queues(sqs_queues)
    lambda_health = lambda_checker.check_functions(lambda_functions)
    
    # Compile results
    health_check_result = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "environment": ENVIRONMENT,
        "services": {
            "dynamodb": dynamodb_health.to_dict(),
            "sqs": sqs_health.to_dict(),
            "lambda": lambda_health.to_dict()
        }
    }
    
    # Determine overall status
    all_services = [dynamodb_health, sqs_health, lambda_health]
    overall_status = HealthStatus.HEALTHY
    
    for service in all_services:
        service_status = service.get_overall_status()
        if service_status == HealthStatus.UNHEALTHY:
            overall_status = HealthStatus.UNHEALTHY
            break
        elif service_status == HealthStatus.UNKNOWN and overall_status == HealthStatus.HEALTHY:
            overall_status = HealthStatus.UNKNOWN
    
    health_check_result["overall_status"] = overall_status.value
    
    logger.info(
        "Health check complete",
        extra={
            "overall_status": overall_status.value,
            "dynamodb_status": dynamodb_health.get_overall_status().value,
            "sqs_status": sqs_health.get_overall_status().value,
            "lambda_status": lambda_health.get_overall_status().value
        }
    )
    
    return health_check_result


@tracer.capture_method
def emit_health_metrics(health_check_result: Dict[str, Any]) -> None:
    """
    Emit health check metrics to CloudWatch.
    
    Args:
        health_check_result: Health check result dictionary
    """
    try:
        # Emit overall health status metric
        is_healthy = health_check_result.get("overall_status") == HealthStatus.HEALTHY.value
        metrics.add_metric(
            name="HealthCheckStatus",
            unit=MetricUnit.Count,
            value=1 if is_healthy else 0
        )
        
        # Emit service-level metrics
        services = health_check_result.get("services", {})
        for service_name, service_data in services.items():
            is_service_healthy = (
                service_data.get("overall_status") == HealthStatus.HEALTHY.value
            )
            metrics.add_metric(
                name=f"{service_name.capitalize()}HealthStatus",
                unit=MetricUnit.Count,
                value=1 if is_service_healthy else 0
            )
            
            # Count unhealthy components
            components = service_data.get("components", {})
            unhealthy_count = sum(
                1 for comp in components.values()
                if comp.get("status") != HealthStatus.HEALTHY.value
            )
            if unhealthy_count > 0:
                metrics.add_metric(
                    name=f"{service_name.capitalize()}UnhealthyComponents",
                    unit=MetricUnit.Count,
                    value=unhealthy_count
                )
        
        logger.info(
            "Health metrics emitted successfully",
            extra={"environment": ENVIRONMENT}
        )
    except Exception as e:
        logger.error(
            "Failed to emit health metrics",
            extra={
                "error": str(e),
                "environment": ENVIRONMENT
            }
        )


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_cold_start_metric
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Lambda handler for health check execution.
    
    Args:
        event: Lambda event (from EventBridge schedule)
        context: Lambda context
        
    Returns:
        Dictionary with status code and health check result
    """
    logger.debug(
        "Health check handler invoked",
        extra={
            "function_name": context.function_name,
            "request_id": context.request_id,
            "memory_limit": context.memory_limit_in_mb
        }
    )
    
    try:
        # Perform health checks
        health_check_result = check_all_services()
        
        # Emit metrics
        emit_health_metrics(health_check_result)
        
        # Determine response status code
        is_healthy = health_check_result.get("overall_status") == HealthStatus.HEALTHY.value
        status_code = 200 if is_healthy else 503
        
        logger.info(
            "Health check completed successfully",
            extra={
                "status_code": status_code,
                "overall_status": health_check_result.get("overall_status")
            }
        )
        
        # Flush metrics before returning
        metrics.flush()
        
        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(health_check_result)
        }
    
    except Exception as e:
        logger.error(
            "Health check handler failed with exception",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        
        # Emit failure metric
        metrics.add_metric(
            name="HealthCheckFailure",
            unit=MetricUnit.Count,
            value=1
        )
        metrics.flush()
        
        # Return unhealthy response
        return {
            "statusCode": 503,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "environment": ENVIRONMENT,
                "overall_status": "unhealthy",
                "error": str(e)
            })
        }
