"""
Health Check Classes and Utilities.

This module provides reusable health check classes for monitoring
DynamoDB tables, SQS queues, and Lambda functions.
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from enum import Enum
import boto3
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger

# Initialize logger
logger = Logger(service="health-check")


class HealthStatus(str, Enum):
    """Enumeration of health status values."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Represents the health status of a single component."""
    name: str
    status: HealthStatus
    details: Dict[str, Any]
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass
class ServiceHealth:
    """Represents the overall health status of a service type."""
    service_type: str
    components: Dict[str, ComponentHealth]
    
    def get_overall_status(self) -> HealthStatus:
        """Determine overall status from all components."""
        if not self.components:
            return HealthStatus.UNKNOWN
        
        if any(comp.status == HealthStatus.UNHEALTHY for comp in self.components.values()):
            return HealthStatus.UNHEALTHY
        
        if all(comp.status == HealthStatus.HEALTHY for comp in self.components.values()):
            return HealthStatus.HEALTHY
        
        return HealthStatus.UNKNOWN
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "service_type": self.service_type,
            "overall_status": self.get_overall_status().value,
            "components": {
                name: comp.to_dict() for name, comp in self.components.items()
            }
        }


class DynamoDBHealthChecker:
    """Health checker for DynamoDB tables."""
    
    def __init__(self):
        """Initialize DynamoDB client."""
        self.client = boto3.client("dynamodb")
    
    def check_table(self, table_name: str) -> ComponentHealth:
        """
        Check health of a single DynamoDB table.
        
        Args:
            table_name: Name of the table to check
            
        Returns:
            ComponentHealth object with status and details
        """
        if not table_name:
            return ComponentHealth(
                name="",
                status=HealthStatus.UNKNOWN,
                details={},
                error="Empty table name provided"
            )
        
        try:
            logger.debug(f"Checking DynamoDB table: {table_name}")
            response = self.client.describe_table(TableName=table_name)
            
            table = response["Table"]
            status = table["TableStatus"]
            
            # Determine health status based on table status
            is_healthy = status == "ACTIVE"
            
            return ComponentHealth(
                name=table_name,
                status=HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY,
                details={
                    "table_status": status,
                    "item_count": table.get("ItemCount", 0),
                    "size_bytes": table.get("TableSizeBytes", 0),
                    "provisioned_throughput": {
                        "read_capacity": table.get("BillingModeSummary", {}).get("ReadCapacityUnits"),
                        "write_capacity": table.get("BillingModeSummary", {}).get("WriteCapacityUnits")
                    }
                }
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.warning(
                f"DynamoDB health check failed for table {table_name}",
                extra={"error_code": error_code, "table_name": table_name}
            )
            return ComponentHealth(
                name=table_name,
                status=HealthStatus.UNHEALTHY,
                details={},
                error=str(e)
            )
        except Exception as e:
            logger.error(
                f"Unexpected error checking DynamoDB table {table_name}",
                extra={"error": str(e), "table_name": table_name}
            )
            return ComponentHealth(
                name=table_name,
                status=HealthStatus.UNHEALTHY,
                details={},
                error=str(e)
            )
    
    def check_tables(self, table_names: List[str]) -> ServiceHealth:
        """
        Check health of multiple DynamoDB tables.
        
        Args:
            table_names: List of table names to check
            
        Returns:
            ServiceHealth object with results for all tables
        """
        components = {}
        for table_name in table_names:
            components[table_name] = self.check_table(table_name)
        
        return ServiceHealth(
            service_type="dynamodb",
            components=components
        )


class SQSHealthChecker:
    """Health checker for SQS queues."""
    
    def __init__(self):
        """Initialize SQS client."""
        self.client = boto3.client("sqs")
    
    def check_queue(self, queue_url: str) -> ComponentHealth:
        """
        Check health of a single SQS queue.
        
        Args:
            queue_url: URL of the queue to check
            
        Returns:
            ComponentHealth object with status and details
        """
        if not queue_url:
            return ComponentHealth(
                name="",
                status=HealthStatus.UNKNOWN,
                details={},
                error="Empty queue URL provided"
            )
        
        try:
            queue_name = queue_url.split("/")[-1]
            logger.debug(f"Checking SQS queue: {queue_name}")
            
            response = self.client.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=["All"]
            )
            
            attrs = response.get("Attributes", {})
            
            # Determine if queue is accessible (accessible == healthy)
            return ComponentHealth(
                name=queue_name,
                status=HealthStatus.HEALTHY,
                details={
                    "messages_available": int(attrs.get("ApproximateNumberOfMessagesVisible", 0)),
                    "messages_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
                    "messages_delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
                    "message_retention_seconds": int(attrs.get("MessageRetentionPeriod", 0)),
                    "visibility_timeout": int(attrs.get("VisibilityTimeout", 0))
                }
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            queue_name = queue_url.split("/")[-1] if queue_url else "unknown"
            logger.warning(
                f"SQS health check failed for queue {queue_name}",
                extra={"error_code": error_code, "queue_url": queue_url}
            )
            return ComponentHealth(
                name=queue_name,
                status=HealthStatus.UNHEALTHY,
                details={},
                error=str(e)
            )
        except Exception as e:
            queue_name = queue_url.split("/")[-1] if queue_url else "unknown"
            logger.error(
                f"Unexpected error checking SQS queue {queue_name}",
                extra={"error": str(e), "queue_url": queue_url}
            )
            return ComponentHealth(
                name=queue_name,
                status=HealthStatus.UNHEALTHY,
                details={},
                error=str(e)
            )
    
    def check_queues(self, queue_urls: List[str]) -> ServiceHealth:
        """
        Check health of multiple SQS queues.
        
        Args:
            queue_urls: List of queue URLs to check
            
        Returns:
            ServiceHealth object with results for all queues
        """
        components = {}
        for queue_url in queue_urls:
            if queue_url:
                queue_name = queue_url.split("/")[-1]
                components[queue_name] = self.check_queue(queue_url)
        
        return ServiceHealth(
            service_type="sqs",
            components=components
        )


class LambdaHealthChecker:
    """Health checker for Lambda functions."""
    
    def __init__(self):
        """Initialize Lambda client."""
        self.client = boto3.client("lambda")
    
    def check_function(self, function_name: str) -> ComponentHealth:
        """
        Check health of a single Lambda function.
        
        Args:
            function_name: Name of the function to check
            
        Returns:
            ComponentHealth object with status and details
        """
        if not function_name:
            return ComponentHealth(
                name="",
                status=HealthStatus.UNKNOWN,
                details={},
                error="Empty function name provided"
            )
        
        try:
            logger.debug(f"Checking Lambda function: {function_name}")
            response = self.client.get_function(FunctionName=function_name)
            
            config = response["Configuration"]
            state = config["State"]
            
            # Determine health based on function state
            is_healthy = state == "Active"
            
            return ComponentHealth(
                name=function_name,
                status=HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY,
                details={
                    "state": state,
                    "runtime": config.get("Runtime"),
                    "memory_size": config.get("MemorySize", 0),
                    "timeout": config.get("Timeout", 0),
                    "last_modified": config.get("LastModified"),
                    "code_sha256": config.get("CodeSha256")
                }
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.warning(
                f"Lambda health check failed for function {function_name}",
                extra={"error_code": error_code, "function_name": function_name}
            )
            return ComponentHealth(
                name=function_name,
                status=HealthStatus.UNHEALTHY,
                details={},
                error=str(e)
            )
        except Exception as e:
            logger.error(
                f"Unexpected error checking Lambda function {function_name}",
                extra={"error": str(e), "function_name": function_name}
            )
            return ComponentHealth(
                name=function_name,
                status=HealthStatus.UNHEALTHY,
                details={},
                error=str(e)
            )
    
    def check_functions(self, function_names: List[str]) -> ServiceHealth:
        """
        Check health of multiple Lambda functions.
        
        Args:
            function_names: List of function names to check
            
        Returns:
            ServiceHealth object with results for all functions
        """
        components = {}
        for function_name in function_names:
            components[function_name] = self.check_function(function_name)
        
        return ServiceHealth(
            service_type="lambda",
            components=components
        )
