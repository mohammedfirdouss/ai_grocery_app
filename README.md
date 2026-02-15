
## Overview

The AI Grocery App is a modern, serverless application that allows users to submit grocery lists via text and automatically processes them using AI (Amazon Bedrock) to match products, calculate prices, and generate payment links through PayStack.

## Features

- **AI-Powered Text Parsing**: Processes natural language grocery lists using Amazon Bedrock
- **Product Matching**: Intelligent matching of grocery items with product catalog
- **Real-time Notifications**: AppSync subscriptions for order status updates
- **Payment Integration**: Seamless PayStack integration for secure payments
- **Event-Driven Architecture**: EventBridge-based event processing
- **Comprehensive Monitoring**: Full observability with CloudWatch, X-Ray, and health checks

## Architecture

The application uses a serverless, event-driven architecture with the following key components:

- **Lambda Functions**: Text parsing, product matching, payment processing, webhooks, event handling
- **DynamoDB**: Orders, products, and payment links storage
- **SQS**: Message queuing for decoupled processing
- **AppSync**: GraphQL API for real-time updates
- **EventBridge**: Event routing and processing
- **X-Ray**: Distributed tracing
- **CloudWatch**: Metrics, logs, and alarms

## Monitoring and Observability

The application includes comprehensive monitoring and observability:

- **CloudWatch Metrics**: Custom metrics for all processing stages
- **CloudWatch Alarms**: Error rate, latency, and throttling alarms
- **CloudWatch Dashboard**: Real-time system health visualization
- **AWS Budgets**: Cost monitoring and alerts
- **Health Checks**: Automated dependency health monitoring
- **X-Ray Tracing**: End-to-end request correlation
- **Structured Logging**: JSON logs with correlation IDs

For detailed information, see:
- [Monitoring Guide](docs/MONITORING.md)
- [Monitoring Architecture](docs/MONITORING_ARCHITECTURE.md)

## Getting Started

### Prerequisites

- AWS Account with appropriate permissions
- Python 3.11+
- Node.js and AWS CDK
- Docker (for LocalStack development)

### Installation

```bash
# Install dependencies
make install

# Set up development environment
make setup-dev

# Deploy to LocalStack
make deploy
```

### Testing

```bash
# Run all tests
make test

# Run specific test suite
python -m pytest tests/test_monitoring.py -v
```

## Development

### Environment Configuration

The application supports three environments: dev, staging, and production.

Configuration is managed in `infrastructure/config/environment_config.py`.

## Deployment

### Deploy to AWS

```bash
# Set AWS credentials
export AWS_PROFILE=your-profile

# Deploy to dev environment
cdk deploy AiGroceryStack-dev --context environment=dev

# Deploy to production
cdk deploy AiGroceryStack-production --context environment=production
```

## Documentation

- [Monitoring Guide](docs/MONITORING.md) - Comprehensive monitoring and observability guide
- [Monitoring Architecture](docs/MONITORING_ARCHITECTURE.md) - Visual architecture diagrams

## Security

The application implements security best practices:

- Encryption at rest (KMS)
- Encryption in transit (TLS)
- Least privilege IAM policies
- Input validation and sanitization
- Secure secrets management (Secrets Manager)
- PayStack webhook signature verification

## License

[License information to be added]
