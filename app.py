#!/usr/bin/env python3
"""
AI Grocery App CDK Application Entry Point

This is the main entry point for the AWS CDK application that deploys
the AI Grocery App infrastructure across multiple environments.
"""

import os
import aws_cdk as cdk
from aws_cdk import Environment

from infrastructure.stacks.ai_grocery_stack import AiGroceryStack
from infrastructure.config.environment_config import EnvironmentConfig


def main():
    """Main application entry point."""
    app = cdk.App()
    
    # Get environment from context or default to 'dev'
    env_name = app.node.try_get_context("environment") or "dev"
    
    # Load environment-specific configuration
    config = EnvironmentConfig.get_config(env_name)
    
    # Define AWS environment
    aws_env = Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", config.aws_region)
    )
    
    # Create the main stack
    AiGroceryStack(
        app,
        f"AiGroceryStack-{env_name}",
        config=config,
        env=aws_env,
        description=f"AI Grocery App infrastructure for {env_name} environment"
    )
    
    app.synth()


if __name__ == "__main__":
    main()