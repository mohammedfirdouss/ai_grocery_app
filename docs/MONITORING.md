# Monitoring and Observability Guide

This document provides a comprehensive overview of the monitoring and observability infrastructure for the AI Grocery App.

## Table of Contents

- [Overview](#overview)
- [CloudWatch Metrics and Alarms](#cloudwatch-metrics-and-alarms)
- [Custom Metrics for Processing Stages](#custom-metrics-for-processing-stages)
- [CloudWatch Dashboard](#cloudwatch-dashboard)
- [Cost Monitoring and Budget Alerts](#cost-monitoring-and-budget-alerts)
- [Health Check Endpoints](#health-check-endpoints)
- [X-Ray Tracing](#x-ray-tracing)
- [Structured Logging](#structured-logging)
- [Configuration](#configuration)

## Overview

The AI Grocery App implements comprehensive monitoring and observability using AWS native services:

- **CloudWatch**: Metrics, alarms, and dashboards
- **X-Ray**: Distributed tracing for request correlation
- **AWS Lambda Powertools**: Structured logging, metrics, and tracing
- **AWS Budgets**: Cost monitoring and alerts
- **EventBridge**: Scheduled health checks

## CloudWatch Metrics and Alarms

### Lambda Function Alarms

For each Lambda function, the following alarms are configured:

#### Error Rate Alarm
- **Metric**: Lambda Errors
- **Threshold**: 5 errors in 10 minutes (2 evaluation periods of 5 minutes)
- **Description**: Triggers when error rate exceeds acceptable limits
- **Action**: Sends notification to SNS alarm topic

#### Latency Alarm
- **Metric**: Lambda Duration (p90)
- **Threshold**: 80% of function timeout
- **Description**: Triggers when p90 latency approaches timeout
- **Evaluation**: 3 consecutive periods of 5 minutes
- **Action**: Sends notification to SNS alarm topic

#### Throttling Alarm
- **Metric**: Lambda Throttles
- **Threshold**: 1 or more throttles
- **Description**: Triggers immediately when function is throttled
- **Action**: Sends notification to SNS alarm topic

### SQS Queue Alarms

#### Dead Letter Queue (DLQ) Messages
- **Metric**: ApproximateNumberOfMessagesVisible
- **Threshold**: 1 or more messages
- **Description**: Alerts on processing failures that land in DLQ
- **Action**: Sends notification to SNS alarm topic

#### Message Age
- **Metric**: ApproximateAgeOfOldestMessage
- **Threshold**: 3600 seconds (1 hour)
- **Description**: Triggers when messages are not being processed timely
- **Evaluation**: 2 consecutive periods of 5 minutes
- **Action**: Sends notification to SNS alarm topic

### DynamoDB Table Alarms

#### Read Throttling
- **Metric**: ReadThrottleEvents
- **Threshold**: 1 or more events
- **Description**: Alerts on read capacity throttling
- **Action**: Sends notification to SNS alarm topic

#### Write Throttling
- **Metric**: WriteThrottleEvents
- **Threshold**: 1 or more events
- **Description**: Alerts on write capacity throttling
- **Action**: Sends notification to SNS alarm topic

#### System Errors
- **Metric**: SystemErrors
- **Threshold**: 1 or more errors
- **Description**: Alerts on DynamoDB system errors
- **Action**: Sends notification to SNS alarm topic

### Alarm Configuration

All alarms:
- Send notifications to the `ai-grocery-alarms-{environment}` SNS topic
- Have `TreatMissingData` set to `notBreaching` to avoid false positives
- Can optionally send email notifications if configured

## Custom Metrics for Processing Stages

Custom metrics are emitted using AWS Lambda Powertools and published to the `AiGroceryApp/{environment}` namespace.

### Text Parser Metrics

- **TextParsingSuccess**: Count of successful text parsing operations
- **TextParsingError**: Count of text parsing failures
- **TextValidationError**: Count of validation failures
- **TextLength**: Character count of processed text
- **LineCount**: Line count of processed text
- **OrderStatusUpdateSuccess**: Successful order status updates
- **OrderStatusUpdateFailure**: Failed order status updates
- **ProductMatcherQueueSendSuccess**: Successful queue sends
- **ProductMatcherQueueSendFailure**: Failed queue sends
- **InvalidMessageFormat**: Messages with invalid format
- **MissingOrderId**: Messages missing order ID
- **MissingCreatedAt**: Messages missing timestamp
- **MissingRawText**: Messages missing text content

### Product Matcher Metrics

- **BedrockInvocationSuccess**: Successful Bedrock API calls
- **BedrockInvocationError**: Failed Bedrock API calls
- **ItemsExtracted**: Count of extracted grocery items
- **ItemsMatched**: Count of successfully matched items
- **ItemsUnmatched**: Count of unmatched items
- **MatchConfidence**: Confidence scores of matches
- **ProcessingDuration**: Time spent processing
- **GuardrailBlocked**: Requests blocked by guardrails
- **RateLimitHit**: Rate limit occurrences

### Payment Processor Metrics

- **PaymentLinkCreated**: Count of created payment links
- **PaymentLinkError**: Payment link creation failures
- **PaymentAmount**: Payment amounts processed

### Payment Webhook Metrics

- **WebhookReceived**: Count of received webhooks
- **WebhookInvalidSignature**: Invalid signature count
- **WebhookProcessingError**: Webhook processing errors
- **PaymentSuccess**: Successful payments
- **PaymentFailed**: Failed payments
- **PaymentAmount**: Payment amounts
- **TransferSuccess**: Successful transfers

### Event Handler Metrics

- **OrderUpdateNotificationPublished**: Published notifications
- **OrderUpdateNotificationFailed**: Failed notifications
- **DynamoDBStreamEventsProcessed**: Processed stream events

## CloudWatch Dashboard

A comprehensive dashboard (`ai-grocery-{environment}-dashboard`) provides real-time visibility into system health.

### Dashboard Sections

#### Lambda Metrics
- **Invocations**: Function invocation counts over time
- **Errors**: Error counts per function
- **Duration (p90)**: 90th percentile latency
- **Concurrent Executions**: Maximum concurrent executions

#### SQS Metrics
- **Queue Depth**: Number of messages in queues
- **Message Age**: Age of oldest message per queue

#### DynamoDB Metrics
- **Read Capacity**: Consumed read capacity units
- **Write Capacity**: Consumed write capacity units

#### Custom Application Metrics
- **Text Parsing Metrics**: Success, errors, and validation failures
- **Order Processing Metrics**: Status updates and queue sends

## Cost Monitoring and Budget Alerts

### Budget Configuration

AWS Budgets are configured for cost monitoring:

- **Budget Name**: `ai-grocery-{environment}-monthly-budget`
- **Budget Type**: COST
- **Time Unit**: MONTHLY
- **Budget Limit**: Configurable per environment (default: $100)

### Budget Alerts

Two notification thresholds are configured:

1. **80% Actual Threshold**
   - Type: ACTUAL
   - Threshold: 80%
   - When actual costs reach 80% of budget, notification is sent

2. **100% Forecasted Threshold**
   - Type: FORECASTED
   - Threshold: 100%
   - When forecasted costs are projected to exceed budget, notification is sent

Notifications are sent via:
- Email (if configured)
- SNS alarm topic

## Health Check Endpoints

### Health Check Lambda

A dedicated Lambda function (`ai-grocery-health-check-{environment}`) performs comprehensive health checks:

#### Monitored Components

1. **DynamoDB Tables**
   - Checks table status (ACTIVE)
   - Reports item count
   - Detects table issues

2. **SQS Queues**
   - Checks queue accessibility
   - Reports message counts (available, in-flight, delayed)
   - Detects queue issues

3. **Lambda Functions**
   - Checks function state (Active)
   - Reports configuration details
   - Detects function issues

#### Health Check Schedule

- **Frequency**: Every 5 minutes
- **Trigger**: EventBridge scheduled rule
- **Timeout**: 30 seconds
- **Memory**: 256 MB

#### Health Check Response

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "environment": "dev",
  "overall_status": "healthy",
  "components": {
    "dynamodb": {
      "table-name": {
        "status": "healthy",
        "table_status": "ACTIVE",
        "item_count": 100
      }
    },
    "sqs": {
      "queue-name": {
        "status": "healthy",
        "messages_available": 0,
        "messages_in_flight": 0,
        "messages_delayed": 0
      }
    },
    "lambda": {
      "function-name": {
        "status": "healthy",
        "state": "Active",
        "runtime": "python3.11",
        "memory_size": 512,
        "timeout": 30,
        "last_modified": "2024-01-15T09:00:00Z"
      }
    }
  }
}
```

#### Health Metrics

The health check Lambda emits a custom metric:
- **Metric Name**: HealthCheckStatus
- **Namespace**: AiGroceryApp/{environment}
- **Value**: 1 (healthy) or 0 (unhealthy)

#### IAM Permissions

The health check Lambda has least-privilege permissions:
- `dynamodb:DescribeTable` on specific table ARNs
- `sqs:GetQueueAttributes` on specific queue ARNs
- `lambda:GetFunction` on specific function ARNs
- `cloudwatch:PutMetricData` restricted to AiGroceryApp namespace
- `xray:PutTraceSegments` and `xray:PutTelemetryRecords` for X-Ray

## X-Ray Tracing

### Configuration

X-Ray tracing is enabled for all Lambda functions and AppSync API:

- **Lambda Tracing Mode**: ACTIVE
- **AppSync X-Ray**: Enabled
- **Configuration Flag**: `enable_xray_tracing` in environment config

### Tracing Coverage

All Lambda functions use AWS Lambda Powertools Tracer:

```python
from aws_lambda_powertools import Tracer

tracer = Tracer(service="service-name")

@tracer.capture_method
def my_function():
    # Function code
    pass
```

This provides:
- Automatic trace context propagation
- Method-level tracing
- Exception capture
- Custom annotations and metadata

### Request Correlation

Correlation IDs are used throughout the system:
- Generated for each new request
- Propagated through all processing stages
- Included in logs and traces
- Used for request correlation in X-Ray

### Viewing Traces

Access X-Ray traces via:
1. AWS X-Ray Console
2. CloudWatch ServiceLens
3. X-Ray API

Traces show:
- End-to-end request flow
- Service call latencies
- Error locations
- DynamoDB operations
- SQS messaging

## Structured Logging

### AWS Lambda Powertools Logger

All Lambda functions use AWS Lambda Powertools Logger for structured logging:

```python
from aws_lambda_powertools import Logger

logger = Logger(service="service-name")

# Structured logging with context
logger.info("Processing order", extra={
    "order_id": order_id,
    "correlation_id": correlation_id,
    "status": "processing"
})
```

### Log Structure

Logs are emitted in JSON format with:
- **timestamp**: ISO 8601 timestamp
- **level**: Log level (INFO, WARNING, ERROR, etc.)
- **service**: Service name
- **message**: Log message
- **correlation_id**: Request correlation ID
- **custom fields**: Any additional context

### Log Retention

CloudWatch Log Groups are configured per environment:
- **Dev**: 7 days
- **Staging**: 30 days
- **Production**: 90 days

### Log Groups

Each Lambda function has its own log group:
- `/aws/lambda/ai-grocery-text-parser-{environment}`
- `/aws/lambda/ai-grocery-product-matcher-{environment}`
- `/aws/lambda/ai-grocery-payment-processor-{environment}`
- `/aws/lambda/ai-grocery-payment-webhook-{environment}`
- `/aws/lambda/ai-grocery-event-handler-{environment}`
- `/aws/lambda/ai-grocery-health-check-{environment}`

### Log Insights Queries

Example queries for CloudWatch Logs Insights:

#### Error Analysis
```
fields @timestamp, level, message, correlation_id
| filter level = "ERROR"
| sort @timestamp desc
| limit 100
```

#### Performance Analysis
```
fields @timestamp, correlation_id, @duration
| filter @type = "REPORT"
| stats avg(@duration), max(@duration), min(@duration) by bin(5m)
```

#### Custom Metric Tracking
```
fields @timestamp, message
| filter message like /PaymentSuccess/
| stats count() by bin(1h)
```

## Configuration

### Environment Configuration

Monitoring settings are configured in `infrastructure/config/environment_config.py`:

```python
@dataclass
class EnvironmentConfig:
    # Monitoring settings
    enable_xray_tracing: bool
    log_retention_days: int
    alarm_email: Optional[str] = None
    monthly_budget_limit: float = 100.0
```

### Per-Environment Settings

#### Development
- X-Ray: Enabled
- Log Retention: 7 days
- Budget: $50
- Alarm Email: Not configured

#### Staging
- X-Ray: Enabled
- Log Retention: 30 days
- Budget: $200
- Alarm Email: Optional

#### Production
- X-Ray: Enabled
- Log Retention: 90 days
- Budget: $1000
- Alarm Email: Required

### Monitored Lambda Functions

The following functions are monitored:
- `text-parser`: Processes grocery list text
- `product-matcher`: Matches items with Bedrock
- `payment-processor`: Creates payment links
- `payment-webhook`: Handles payment webhooks
- `event-handler`: Processes events and notifications
- `health-check`: Performs health checks

### Alarm Recipients

Configure alarm notifications by setting the `alarm_email` in your environment:

```python
config = EnvironmentConfig(
    # ... other settings
    alarm_email="ops-team@example.com"
)
```

## Best Practices

1. **Monitor Proactively**: Review dashboard regularly
2. **Set Appropriate Thresholds**: Tune alarm thresholds based on actual usage
3. **Investigate Alarms Promptly**: Don't ignore recurring alarms
4. **Use Correlation IDs**: Always log and trace with correlation IDs
5. **Review Health Checks**: Monitor health check results for trends
6. **Analyze Cost Trends**: Review budget alerts and optimize costs
7. **Use X-Ray for Debugging**: Leverage traces for troubleshooting
8. **Query Logs Regularly**: Use CloudWatch Logs Insights for analysis
9. **Keep Retention Appropriate**: Balance cost with compliance needs
10. **Document Incidents**: Track patterns and improve monitoring

## Troubleshooting

### High Error Rates

1. Check CloudWatch Logs for error details
2. Review X-Ray traces for failing requests
3. Examine custom metrics for specific failure types
4. Check DLQ messages for failed processing

### Performance Issues

1. Review Lambda Duration metrics
2. Analyze X-Ray traces for slow operations
3. Check DynamoDB throttling metrics
4. Review SQS message age metrics

### Cost Overruns

1. Review CloudWatch metrics usage
2. Analyze Lambda invocation patterns
3. Check DynamoDB capacity consumption
4. Review S3 storage costs (if applicable)

### Health Check Failures

1. Check health check Lambda logs
2. Verify IAM permissions
3. Test individual component access
4. Review component-specific metrics

## Additional Resources

- [AWS CloudWatch Documentation](https://docs.aws.amazon.com/cloudwatch/)
- [AWS X-Ray Documentation](https://docs.aws.amazon.com/xray/)
- [AWS Lambda Powertools Documentation](https://awslabs.github.io/aws-lambda-powertools-python/)
- [AWS Budgets Documentation](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)
