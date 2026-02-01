# AI Grocery App Development Makefile

.PHONY: help install setup-dev start-localstack stop-localstack deploy test clean

# Default target
help:
	@echo "AI Grocery App Development Commands"
	@echo "=================================="
	@echo "install        - Install Python dependencies"
	@echo "setup-dev      - Set up development environment with LocalStack"
	@echo "start-localstack - Start LocalStack services"
	@echo "stop-localstack  - Stop LocalStack services"
	@echo "deploy         - Deploy CDK stack to LocalStack"
	@echo "test           - Run all tests"
	@echo "clean          - Clean up temporary files"
	@echo "bootstrap      - Bootstrap CDK for LocalStack"

# Install dependencies
install:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

# Set up development environment
setup-dev: start-localstack
	@echo "Setting up development environment..."
	python scripts/setup-dev.py

# Start LocalStack
start-localstack:
	@echo "Starting LocalStack..."
	docker-compose -f docker-compose.localstack.yml up -d
	@echo "Waiting for LocalStack to be ready..."
	@sleep 10

# Stop LocalStack
stop-localstack:
	@echo "Stopping LocalStack..."
	docker-compose -f docker-compose.localstack.yml down

# Bootstrap CDK
bootstrap:
	@echo "Bootstrapping CDK for LocalStack..."
	export AWS_ENDPOINT_URL=http://localhost:4566 && \
	export CDK_DEFAULT_ACCOUNT=000000000000 && \
	export CDK_DEFAULT_REGION=us-east-1 && \
	cdk bootstrap --context environment=dev

# Deploy CDK stack
deploy:
	@echo "Deploying CDK stack to LocalStack..."
	export AWS_ENDPOINT_URL=http://localhost:4566 && \
	export CDK_DEFAULT_ACCOUNT=000000000000 && \
	export CDK_DEFAULT_REGION=us-east-1 && \
	cdk deploy AiGroceryStack-dev --require-approval never --context environment=dev

# Run tests
test:
	@echo "Running tests..."
	python -m pytest tests/ -v

# Clean up
clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf cdk.out/
	rm -rf tmp/

# Lint code
lint:
	@echo "Linting code..."
	flake8 src/ infrastructure/ tests/
	black --check src/ infrastructure/ tests/
	mypy src/ infrastructure/

# Format code
format:
	@echo "Formatting code..."
	black src/ infrastructure/ tests/
	isort src/ infrastructure/ tests/