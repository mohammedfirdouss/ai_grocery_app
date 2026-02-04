"""
Security infrastructure construct for the AI Grocery App.

This module provides AWS WAF configuration for API protection including:
- Rate limiting rules
- SQL injection protection
- XSS protection
- IP reputation blocking
- Custom rules for AppSync API
"""

from aws_cdk import (
    Stack,
    aws_wafv2 as wafv2,
    CfnOutput,
)
from constructs import Construct
from typing import Optional, List


class SecurityConstruct(Construct):
    """
    CDK Construct for security infrastructure.
    
    Implements:
    - AWS WAF WebACL for AppSync API protection
    - Rate limiting rules
    - Managed rule sets for common vulnerabilities
    - Custom security rules
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        appsync_api_arn: str,
        rate_limit_requests: int = 2000,
        max_request_body_size: int = 262144,  # 256KB default
        block_by_country: Optional[List[str]] = None,
        **kwargs
    ) -> None:
        """
        Initialize the security construct.
        
        Args:
            scope: CDK scope.
            construct_id: Construct ID.
            env_name: Environment name (dev, staging, production).
            appsync_api_arn: ARN of the AppSync API to protect.
            rate_limit_requests: Number of requests per 5-minute window per IP.
            max_request_body_size: Maximum request body size in bytes (default: 256KB).
            block_by_country: Optional list of country codes to block.
        """
        super().__init__(scope, construct_id, **kwargs)
        
        self.env_name = env_name
        self.appsync_api_arn = appsync_api_arn
        self.max_request_body_size = max_request_body_size
        
        # Create WAF WebACL
        self.web_acl = self._create_web_acl(rate_limit_requests, block_by_country)
        
        # Associate WAF with AppSync API
        self._create_waf_association()
    
    def _create_web_acl(
        self,
        rate_limit_requests: int,
        block_by_country: Optional[List[str]]
    ) -> wafv2.CfnWebACL:
        """Create WAF WebACL with security rules."""
        
        rules: List[wafv2.CfnWebACL.RuleProperty] = []
        priority = 0
        
        # Rule 1: Rate limiting
        rules.append(
            wafv2.CfnWebACL.RuleProperty(
                name="RateLimitRule",
                priority=priority,
                action=wafv2.CfnWebACL.RuleActionProperty(
                    block={}
                ),
                statement=wafv2.CfnWebACL.StatementProperty(
                    rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                        limit=rate_limit_requests,
                        aggregate_key_type="IP"
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"ai-grocery-{self.env_name}-rate-limit",
                    sampled_requests_enabled=True
                )
            )
        )
        priority += 1
        
        # Rule 2: AWS Managed Rules - Common Rule Set
        rules.append(
            wafv2.CfnWebACL.RuleProperty(
                name="AWSManagedRulesCommonRuleSet",
                priority=priority,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(
                    none={}
                ),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name="AWSManagedRulesCommonRuleSet",
                        excluded_rules=[]
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"ai-grocery-{self.env_name}-common-rules",
                    sampled_requests_enabled=True
                )
            )
        )
        priority += 1
        
        # Rule 3: AWS Managed Rules - Known Bad Inputs
        rules.append(
            wafv2.CfnWebACL.RuleProperty(
                name="AWSManagedRulesKnownBadInputsRuleSet",
                priority=priority,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(
                    none={}
                ),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name="AWSManagedRulesKnownBadInputsRuleSet",
                        excluded_rules=[]
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"ai-grocery-{self.env_name}-known-bad-inputs",
                    sampled_requests_enabled=True
                )
            )
        )
        priority += 1
        
        # Rule 4: AWS Managed Rules - SQL Injection
        rules.append(
            wafv2.CfnWebACL.RuleProperty(
                name="AWSManagedRulesSQLiRuleSet",
                priority=priority,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(
                    none={}
                ),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name="AWSManagedRulesSQLiRuleSet",
                        excluded_rules=[]
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"ai-grocery-{self.env_name}-sqli-rules",
                    sampled_requests_enabled=True
                )
            )
        )
        priority += 1
        
        # Rule 5: AWS Managed Rules - Amazon IP Reputation List
        rules.append(
            wafv2.CfnWebACL.RuleProperty(
                name="AWSManagedRulesAmazonIpReputationList",
                priority=priority,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(
                    none={}
                ),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name="AWSManagedRulesAmazonIpReputationList",
                        excluded_rules=[]
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"ai-grocery-{self.env_name}-ip-reputation",
                    sampled_requests_enabled=True
                )
            )
        )
        priority += 1
        
        # Rule 6: Custom rule to block large request bodies (GraphQL abuse protection)
        rules.append(
            wafv2.CfnWebACL.RuleProperty(
                name="BlockLargeRequests",
                priority=priority,
                action=wafv2.CfnWebACL.RuleActionProperty(
                    block={}
                ),
                statement=wafv2.CfnWebACL.StatementProperty(
                    size_constraint_statement=wafv2.CfnWebACL.SizeConstraintStatementProperty(
                        field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(
                            body=wafv2.CfnWebACL.BodyProperty(
                                oversize_handling="MATCH"
                            )
                        ),
                        comparison_operator="GT",
                        size=self.max_request_body_size,  # Configurable max request body
                        text_transformations=[
                            wafv2.CfnWebACL.TextTransformationProperty(
                                priority=0,
                                type="NONE"
                            )
                        ]
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"ai-grocery-{self.env_name}-large-requests",
                    sampled_requests_enabled=True
                )
            )
        )
        priority += 1
        
        # Rule 7: Geographic blocking (if specified)
        if block_by_country and len(block_by_country) > 0:
            rules.append(
                wafv2.CfnWebACL.RuleProperty(
                    name="GeoBlockRule",
                    priority=priority,
                    action=wafv2.CfnWebACL.RuleActionProperty(
                        block={}
                    ),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        geo_match_statement=wafv2.CfnWebACL.GeoMatchStatementProperty(
                            country_codes=block_by_country
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"ai-grocery-{self.env_name}-geo-block",
                        sampled_requests_enabled=True
                    )
                )
            )
        
        # Create the WebACL
        web_acl = wafv2.CfnWebACL(
            self,
            "AppSyncWebACL",
            name=f"ai-grocery-appsync-waf-{self.env_name}",
            description=f"WAF WebACL for AI Grocery App AppSync API ({self.env_name})",
            scope="REGIONAL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(
                allow={}
            ),
            rules=rules,
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name=f"ai-grocery-{self.env_name}-waf",
                sampled_requests_enabled=True
            ),
            tags=[
                {"key": "Environment", "value": self.env_name},
                {"key": "Service", "value": "ai-grocery-app"},
                {"key": "Component", "value": "security"}
            ]
        )
        
        return web_acl
    
    def _create_waf_association(self) -> None:
        """Associate WAF WebACL with AppSync API."""
        wafv2.CfnWebACLAssociation(
            self,
            "AppSyncWAFAssociation",
            resource_arn=self.appsync_api_arn,
            web_acl_arn=self.web_acl.attr_arn
        )


class ThrottlingConfig:
    """
    Configuration for API throttling.
    
    This class provides recommended throttling settings for different
    environments and use cases.
    """
    
    # Default throttling configurations by environment
    DEFAULTS = {
        "dev": {
            "rate_limit_requests": 1000,  # Lower for development
            "burst_limit": 50,
            "max_request_body_size": 131072,  # 128KB for dev
        },
        "staging": {
            "rate_limit_requests": 2000,
            "burst_limit": 100,
            "max_request_body_size": 262144,  # 256KB for staging
        },
        "production": {
            "rate_limit_requests": 5000,
            "burst_limit": 500,
            "max_request_body_size": 524288,  # 512KB for production
        }
    }
    
    @classmethod
    def get_config(cls, env_name: str) -> dict:
        """Get throttling configuration for the specified environment."""
        return cls.DEFAULTS.get(env_name, cls.DEFAULTS["dev"])


# WAF rule priority guidelines:
# 0-9: Rate limiting and DDoS protection
# 10-19: IP reputation and geographic rules
# 20-29: Managed rule sets (AWS)
# 30-39: Custom security rules
# 40-49: Application-specific rules
