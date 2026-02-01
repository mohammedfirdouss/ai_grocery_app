#!/usr/bin/env python3
"""
Development environment setup script for AI Grocery App.

This script sets up the local development environment with LocalStack,
creates necessary AWS resources, and populates test data.
"""

import os
import sys
import subprocess
import time
import boto3
from decimal import Decimal
from datetime import datetime, timedelta
import json

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from models.core import Product


def run_command(command, check=True):
    """Run shell command and return result."""
    print(f"Running: {command}")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error running command: {command}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        sys.exit(1)
    return result


def wait_for_localstack():
    """Wait for LocalStack to be ready."""
    print("Waiting for LocalStack to be ready...")
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            # Test LocalStack health endpoint
            import requests
            response = requests.get("http://localhost:4566/_localstack/health")
            if response.status_code == 200:
                print("LocalStack is ready!")
                return True
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_attempts}: LocalStack not ready yet...")
            time.sleep(2)
    
    print("LocalStack failed to start within timeout")
    return False


def setup_aws_clients():
    """Set up AWS clients for LocalStack."""
    session = boto3.Session()
    
    # Configure for LocalStack
    config = {
        'region_name': 'us-east-1',
        'endpoint_url': 'http://localhost:4566',
        'aws_access_key_id': 'test',
        'aws_secret_access_key': 'test'
    }
    
    return {
        'dynamodb': session.client('dynamodb', **config),
        'sqs': session.client('sqs', **config),
        'ssm': session.client('ssm', **config),
        'secretsmanager': session.client('secretsmanager', **config),
        'kms': session.client('kms', **config)
    }


def create_sample_products(dynamodb_client):
    """Create sample products in the products table."""
    table_name = "ai-grocery-products-dev"
    
    sample_products = [
        Product(
            id="prod-001",
            name="Organic Bananas",
            description="Fresh organic bananas, perfect for smoothies and snacks",
            category="Fruits",
            unit_price=Decimal("2.99"),
            unit_of_measure="bunch",
            tags=["organic", "fruit", "banana", "fresh"]
        ),
        Product(
            id="prod-002",
            name="Whole Milk",
            description="Fresh whole milk, 1 gallon",
            category="Dairy",
            unit_price=Decimal("4.49"),
            unit_of_measure="gallon",
            tags=["milk", "dairy", "whole", "fresh"]
        ),
        Product(
            id="prod-003",
            name="Sourdough Bread",
            description="Artisan sourdough bread loaf",
            category="Bakery",
            unit_price=Decimal("5.99"),
            unit_of_measure="loaf",
            tags=["bread", "sourdough", "artisan", "bakery"]
        ),
        Product(
            id="prod-004",
            name="Free Range Eggs",
            description="Free range chicken eggs, dozen",
            category="Dairy",
            unit_price=Decimal("6.99"),
            unit_of_measure="dozen",
            tags=["eggs", "free-range", "chicken", "protein"]
        ),
        Product(
            id="prod-005",
            name="Organic Spinach",
            description="Fresh organic baby spinach leaves",
            category="Vegetables",
            unit_price=Decimal("3.49"),
            unit_of_measure="bag",
            tags=["spinach", "organic", "leafy", "green", "vegetable"]
        )
    ]
    
    print(f"Creating sample products in {table_name}...")
    
    for product in sample_products:
        item = {
            'product_id': {'S': product.id},
            'name': {'S': product.name},
            'description': {'S': product.description},
            'category': {'S': product.category},
            'unit_price': {'N': str(product.unit_price)},
            'currency': {'S': product.currency},
            'unit_of_measure': {'S': product.unit_of_measure},
            'availability': {'BOOL': product.availability},
            'tags': {'SS': product.tags},
            'created_at': {'S': product.created_at.isoformat()},
            'updated_at': {'S': product.updated_at.isoformat()}
        }
        
        try:
            dynamodb_client.put_item(TableName=table_name, Item=item)
            print(f"Created product: {product.name}")
        except Exception as e:
            print(f"Error creating product {product.name}: {e}")


def setup_secrets(secretsmanager_client):
    """Set up development secrets."""
    secrets = {
        "ai-grocery/dev/paystack-api-key": {
            "SecretString": json.dumps({
                "secret_key": "sk_test_your_test_secret_key_here",
                "public_key": "pk_test_your_test_public_key_here"
            })
        },
        "ai-grocery/dev/bedrock-config": {
            "SecretString": json.dumps({
                "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "max_tokens": 4096,
                "temperature": 0.1
            })
        }
    }
    
    print("Setting up development secrets...")
    
    for secret_name, secret_value in secrets.items():
        try:
            secretsmanager_client.create_secret(
                Name=secret_name,
                Description=f"Development secret for {secret_name}",
                **secret_value
            )
            print(f"Created secret: {secret_name}")
        except Exception as e:
            if "already exists" in str(e):
                print(f"Secret {secret_name} already exists, updating...")
                try:
                    secretsmanager_client.update_secret(
                        SecretId=secret_name,
                        **secret_value
                    )
                    print(f"Updated secret: {secret_name}")
                except Exception as update_e:
                    print(f"Error updating secret {secret_name}: {update_e}")
            else:
                print(f"Error creating secret {secret_name}: {e}")


def main():
    """Main setup function."""
    print("Setting up AI Grocery App development environment...")
    
    # Check if LocalStack is running
    if not wait_for_localstack():
        print("Please start LocalStack first:")
        print("docker-compose -f docker-compose.localstack.yml up -d")
        sys.exit(1)
    
    # Deploy CDK stack to LocalStack
    print("Deploying CDK stack to LocalStack...")
    os.environ['AWS_ENDPOINT_URL'] = 'http://localhost:4566'
    os.environ['CDK_DEFAULT_ACCOUNT'] = '000000000000'
    os.environ['CDK_DEFAULT_REGION'] = 'us-east-1'
    
    # Bootstrap CDK (if needed)
    print("Bootstrapping CDK...")
    run_command("cdk bootstrap --context environment=dev", check=False)
    
    # Deploy the stack
    print("Deploying stack...")
    result = run_command("cdk deploy AiGroceryStack-dev --require-approval never --context environment=dev", check=False)
    
    if result.returncode != 0:
        print("CDK deployment failed. This is expected for the first run.")
        print("The infrastructure will be created in subsequent tasks.")
    
    # Set up AWS clients
    aws_clients = setup_aws_clients()
    
    # Wait a bit for resources to be ready
    time.sleep(5)
    
    # Create sample data
    try:
        create_sample_products(aws_clients['dynamodb'])
    except Exception as e:
        print(f"Note: Could not create sample products (table may not exist yet): {e}")
    
    # Set up secrets
    try:
        setup_secrets(aws_clients['secretsmanager'])
    except Exception as e:
        print(f"Note: Could not create secrets (service may not be ready): {e}")
    
    print("\nDevelopment environment setup complete!")
    print("\nNext steps:")
    print("1. Install Python dependencies: pip install -r requirements.txt")
    print("2. Run tests: python -m pytest tests/")
    print("3. Deploy individual components as you implement them")
    print("\nLocalStack is running at: http://localhost:4566")
    print("LocalStack dashboard: http://localhost:4566/_localstack/cockpit")


if __name__ == "__main__":
    main()