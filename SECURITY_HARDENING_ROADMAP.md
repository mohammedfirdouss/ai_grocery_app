# Security Hardening Roadmap (Priority 1 - Task 14)

**Objective:** Implement comprehensive security controls before production deployment  
**Est. Duration:** 3-4 days  
**Critical Path:** Must complete before production deployment

---

## Overview: What Needs Securing

Your infrastructure has the **foundation** (KMS, Secrets Manager, encryption at rest), but needs **hardening** (API protection, audit trails, access control). This roadmap details exactly what to implement.

---

## Section 1: API Security Controls (2 days)

### 1.1 AppSync GraphQL Mutation Throttling

**Current State:** No mutation rate limiting configured  
**Risk:** Expensive queries could DOS the API or cost spikes

**Implementation:**
```python
# File: infrastructure/stacks/ai_grocery_stack.py
# Location: _create_appsync_api() method, after graphql_api creation

graphql_api.add_authorization(
    auth_type=appsync.AuthorizationType.API_KEY,  # For testing only - use Cognito in production
    token_validity=Duration.hours(24)
)

# Add WAF to protect the API
from aws_cdk import aws_wafv2 as wafv2

waf = wafv2.CfnWebACL(
    self,
    "AppSyncWAF",
    scope="REGIONAL",
    default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
        sampled_requests_enabled=True,
        cloudwatch_metrics_enabled=True,
        metric_name="AppSyncWAFMetrics"
    ),
    rules=[
        # Rate limiting rule
        wafv2.CfnWebACL.RuleProperty(
            name="RateLimitRule",
            priority=1,
            statement=wafv2.CfnWebACL.StatementProperty(
                rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                    limit=2000,  # Requests per 5 minutes
                    aggregate_key_type="IP"
                )
            ),
            action=wafv2.CfnWebACL.RuleActionProperty(
                block={}
            ),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloudwatch_metrics_enabled=True,
                metric_name="RateLimitRule"
            )
        ),
        # SQL injection protection
        wafv2.CfnWebACL.RuleProperty(
            name="AWSManagedRulesSQLiProtection",
            priority=2,
            statement=wafv2.CfnWebACL.StatementProperty(
                managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                    vendor_name="AWS",
                    name="AWSManagedRulesSQLiRuleSet"
                )
            ),
            override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloudwatch_metrics_enabled=True,
                metric_name="SQLiProtection"
            )
        ),
        # Request size limit
        wafv2.CfnWebACL.RuleProperty(
            name="RequestSizeLimit",
            priority=3,
            statement=wafv2.CfnWebACL.StatementProperty(
                size_constraint_statement=wafv2.CfnWebACL.SizeConstraintStatementProperty(
                    field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(body={}),
                    comparison_operator="GT",
                    size=8192,  # 8KB max request body
                    text_transformation=[
                        wafv2.CfnWebACL.TextTransformationProperty(
                            priority=0,
                            type="NONE"
                        )
                    ]
                )
            ),
            action=wafv2.CfnWebACL.RuleActionProperty(block={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloudwatch_metrics_enabled=True,
                metric_name="RequestSizeLimit"
            )
        )
    ]
)

# Associate WAF with AppSync
wafv2.CfnWebACLAssociation(
    self,
    "AppSyncWAFAssociation",
    resource_arn=graphql_api.api_arn,
    web_acl_arn=waf.attr_arn
)
```

**Testing:**
```bash
# Test rate limiting (should fail after 2000 requests in 5 min)
for i in {1..100}; do
  aws appsync start-graphql-query \
    --api-id YOUR_API_ID \
    --query '{ orders { items { order_id } } }'
done

# Test request size limit (should fail)
# Large query with depth > 8KB
```

### 1.2 Input Validation & Sanitization

**Current State:** Basic validation in Pydantic models, no GraphQL validation  
**Risk:** Malformed/malicious input could crash processing

**Implementation:**

File: `infrastructure/stacks/ai_grocery_stack.py` - Update GraphQL schema validation:

```python
# In _create_appsync_api(), add input validation to schema:

schema_definition = """
type Query {
  getOrder(orderId: String!): Order
  listOrders(limit: Int = 10, nextToken: String): OrderConnection
  getProduct(productId: String!): Product
}

type Mutation {
  submitGroceryList(
    input: SubmitGroceryListInput!
  ): Order!
  
  confirmPayment(
    orderId: String!
    paymentId: String!
  ): Payment!
}

input SubmitGroceryListInput {
  customerEmail: String!  # @pattern: ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$
  groceryList: String!   # @length: min=1, max=5000
  customerId: String     # @pattern: ^[a-zA-Z0-9_-]+$
}

type Order {
  orderId: String!
  customerId: String
  customerEmail: String!
  status: OrderStatus!
  items: [OrderItem!]!
  totalPrice: Float!
  currency: String!
  createdAt: AWSDateTime!
  updatedAt: AWSDateTime!
}

enum OrderStatus {
  PENDING_MATCHING
  MATCHED
  PAYMENT_INITIATED
  PAYMENT_COMPLETED
  PAYMENT_FAILED
  PROCESSING
  COMPLETED
  CANCELLED
  ERROR
}

type OrderItem {
  itemId: String!
  originalItem: String!
  matchedProduct: MatchedProduct!
  quantity: Float!
  price: Float!
  notes: String
}

type MatchedProduct {
  productId: String!
  name: String!
  category: String!
  price: Float!
  availability: String!
  alternatives: [AlternativeProduct!]
}

type AlternativeProduct {
  productId: String!
  name: String!
  price: Float!
  similarity: Float!
}

type Payment {
  paymentId: String!
  orderId: String!
  amount: Float!
  currency: String!
  status: PaymentStatus!
  paymentLink: String!
  expiresAt: AWSDateTime!
}

enum PaymentStatus {
  INITIATED
  PENDING
  COMPLETED
  FAILED
  EXPIRED
}

type OrderConnection {
  items: [Order!]!
  nextToken: String
  total: Int!
}
"""

# Resolver input validation
submit_order_input_validation = """
{
  "version": "2018-05-29",
  "queries": [
    {
      "type": "String",
      "field": "input.customerEmail",
      "pattern": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\\\.[a-zA-Z]{2,}$",
      "errorMessage": "Invalid email format"
    },
    {
      "type": "String",
      "field": "input.groceryList",
      "minLength": 1,
      "maxLength": 5000,
      "errorMessage": "Grocery list must be between 1 and 5000 characters"
    }
  ]
}
"""
```

File: `src/lambdas/text_parser/handler.py` - Add input validation:

```python
# Add to handler.py
from pydantic import BaseModel, Field, validator
import re

class GroceryListInput(BaseModel):
    customer_email: str = Field(..., regex=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    grocery_list: str = Field(..., min_length=1, max_length=5000)
    customer_id: Optional[str] = Field(None, regex=r"^[a-zA-Z0-9_-]+$")
    
    @validator('grocery_list')
    def sanitize_grocery_list(cls, v):
        # Remove control characters
        v = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', v)
        # Remove excessive whitespace
        v = re.sub(r'\s+', ' ', v).strip()
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_email": "user@example.com",
                "grocery_list": "2 cups milk, 1 loaf bread, 3 eggs"
            }
        }

# In lambda_handler:
try:
    input_data = GroceryListInput(**event)
except ValidationError as e:
    logger.error("Invalid input", extra={"errors": e.errors()})
    raise ValueError(f"Input validation failed: {e}")
```

### 1.3 Cognito User Pool Hardening

**Current State:** Cognito pool exists but not optimized for security  
**Risk:** Weak passwords, account takeovers

**Implementation:**

```python
# File: infrastructure/stacks/ai_grocery_stack.py
# Update _create_cognito_user_pool() method

user_pool = cognito.UserPool(
    self,
    "AiGroceryUserPool",
    user_pool_name=f"ai-grocery-users-{self.env_name}",
    # Password policy
    password_policy=cognito.PasswordPolicy(
        min_length=12,
        require_lowercase=True,
        require_uppercase=True,
        require_digits=True,
        require_symbols=True
    ),
    # Prevent account enumeration
    account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
    # Enable MFA
    mfa=cognito.Mfa.REQUIRED,
    mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
    # Account lockout after failed attempts
    user_invitation=cognito.UserInvitationConfig(
        email_subject="Welcome to AI Grocery App",
        email_body="You have been invited. Your username is {username} and temporary password is {####}"
    ),
    sign_in_aliases=cognito.SignInAliases(email=True, username=False),
    # Enable user attribute changes
    standard_attributes=cognito.StandardAttributes(
        email=cognito.StandardAttribute(required=True, mutable=False),
        email_verified=cognito.StandardAttribute(mutable=True),
        given_name=cognito.StandardAttribute(mutable=True),
        family_name=cognito.StandardAttribute(mutable=True),
    ),
    # Custom attributes
    custom_attributes={
        "customer_id": cognito.StringAttribute(mutable=True, required=False)
    }
)

# Add device tracking
user_pool.add_domain(
    "UserPoolDomain",
    cognito_domain=cognito.CognitoDomainOptions(
        domain_prefix=f"ai-grocery-{self.env_name}"
    )
)

# Create user pool client with security settings
client = user_pool.add_client(
    "WebClient",
    user_pool_client_name="ai-grocery-web",
    auth_flows=cognito.AuthFlow(
        user_password=False,  # Prevent password flow
        admin_user_password=False,
        custom=False,
        allow_refresh_token_auth=True,
        allow_user_password_auth=False,
        allow_user_srp_auth=True
    ),
    access_token_validity=Duration.hours(1),
    refresh_token_validity=Duration.days(30),
    id_token_validity=Duration.hours(1),
    prevent_user_existence_errors=True  # Prevent enumeration
)

# Add resource server for API access control
resource_server = user_pool.add_resource_server(
    "ApiResourceServer",
    identifier="ai-grocery-api",
    scopes=[
        cognito.ResourceServerScope(scope_name="read", description="Read orders and products"),
        cognito.ResourceServerScope(scope_name="write", description="Submit orders and payments"),
        cognito.ResourceServerScope(scope_name="admin", description="Admin operations")
    ]
)
```

---

## Section 2: Audit & Compliance Logging (1 day)

### 2.1 CloudTrail Setup

**Purpose:** Track all API calls for compliance & incident investigation

```python
# File: infrastructure/stacks/ai_grocery_stack.py
# Add to __init__:

from aws_cdk import aws_s3 as s3, aws_cloudtrail as cloudtrail

# Create S3 bucket for CloudTrail logs
trail_bucket = s3.Bucket(
    self,
    "CloudTrailBucket",
    bucket_name=f"ai-grocery-cloudtrail-{self.env_name}-{self.account}",
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    encryption=s3.BucketEncryption.KMS,
    encryption_key=self.kms_key,
    versioned=True,
    lifecycle_rules=[
        s3.LifecycleRule(
            transitions=[
                s3.Transition(
                    storage_class=s3.StorageClass.INTELLIGENT_TIERING,
                    transition_after=Duration.days(30)
                ),
                s3.Transition(
                    storage_class=s3.StorageClass.GLACIER,
                    transition_after=Duration.days(90)
                )
            ],
            expiration=Duration.days(365)
        )
    ]
)

# Create CloudTrail
trail = cloudtrail.Trail(
    self,
    "AiGroceryTrail",
    bucket=trail_bucket,
    is_multi_region_trail=True,
    include_global_service_events=True,
    enable_file_validation=True,
    send_to_cloud_watch_logs=True
)

# Add specific event selectors for important services
trail.add_s3_event_selector([
    cloudtrail.S3EventSelector(
        s3_selector=[
            cloudtrail.S3EventSelectorOptions(
                bucket=trail_bucket,
                object_prefix="",
                include_management_events=True
            )
        ]
    )
]
```

### 2.2 Lambda Function Audit Logging

**Purpose:** Track sensitive operations in application code

File: `src/lambdas/text_parser/handler.py` - Add audit logging:

```python
from aws_lambda_powertools.utilities.parameters import get_parameter
import json
from datetime import datetime

# Add to lambda_handler:
def log_audit(event_type: str, details: dict, severity: str = "INFO"):
    """
    Log security-relevant events for audit trail.
    
    Args:
        event_type: Type of event (e.g., "PAYMENT_INITIATED", "DATA_ACCESS")
        details: Event details as dict
        severity: "INFO", "WARNING", "ERROR", "CRITICAL"
    """
    audit_log = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        "severity": severity,
        "request_id": context.request_id,
        "user_id": event.get("user_id"),
        "details": details,
        "function": context.function_name,
        "version": context.function_version
    }
    
    # Log to CloudWatch with structured format
    if severity == "CRITICAL":
        logger.critical(json.dumps(audit_log))
    elif severity == "WARNING":
        logger.warning(json.dumps(audit_log))
    else:
        logger.info(json.dumps(audit_log))

# Example usage in payment handler:
log_audit(
    event_type="PAYMENT_LINK_CREATED",
    details={
        "order_id": order_id,
        "amount": payment_details["amount"],
        "customer_email": order["customer_email"],
        "payment_gateway": "paystack"
    }
)

log_audit(
    event_type="UNAUTHORIZED_ACCESS_ATTEMPT",
    details={"customer_email": attempted_email, "reason": "missing_auth_token"},
    severity="WARNING"
)
```

### 2.3 CloudWatch Log Analysis & Alerts

File: `infrastructure/monitoring/monitoring_construct.py` - Add security-focused alarms:

```python
# Create metric filters for security events
from aws_cdk import aws_logs as logs

# Filter for unauthorized access attempts
unauthorized_filter = logs.MetricFilter(
    self,
    "UnauthorizedAccessFilter",
    log_group=text_parser_log_group,
    metric_namespace="AiGroceryApp/Security",
    metric_name="UnauthorizedAccessAttempts",
    filter_pattern=logs.FilterPattern.literal('[time, request_id, level = "WARNING" || level = "ERROR", msg = "*UNAUTHORIZED*", ...]'),
    metric_value="1"
)

# Alarm for unauthorized access
unauthorized_alarm = cloudwatch.Alarm(
    self,
    "UnauthorizedAccessAlarm",
    metric=unauthorized_filter.metric(),
    threshold=5,
    evaluation_periods=1,
    datapoints_to_alarm=1,
    alarm_name=f"ai-grocery-unauthorized-access-{self.env_name}",
    alarm_description="Alert when unauthorized access attempts exceed threshold"
)

# Route to SNS
unauthorized_alarm.add_alarm_action(
    cloudwatch_actions.SnsAction(self.alarm_sns_topic)
)
```

---

## Section 3: Data Access Control & Encryption (1 day)

### 3.1 AppSync Resolver Authorization

**Current Issue:** Resolvers don't verify customer owns the data they're requesting

File: `infrastructure/stacks/ai_grocery_stack.py` - Update GraphQL resolvers:

```python
# In _create_appsync_api(), update order query resolver:

get_order_resolver = orders_data_source.create_resolver(
    "GetOrderResolver",
    api=graphql_api,
    type_name="Query",
    field_name="getOrder",
    request_mapping_template=appsync.MappingTemplate.from_string("""
        {
            "version": "2018-05-29",
            "operation": "GetItem",
            "key": {
                "order_id": $util.dynamodb.toDynamoDBJson($ctx.args.orderId)
            }
        }
    """),
    response_mapping_template=appsync.MappingTemplate.from_string("""
        #if($ctx.result)
            #set($customerId = $ctx.result.customer_id)
            #set($authUserId = $ctx.identity.sub)
            
            #if($customerId == $authUserId || $ctx.identity.claims.get("admin"))
                $util.toJson($ctx.result)
            #else
                $util.unauthorized()
            #end
        #else
            $util.error("Order not found")
        #end
    """)
)

# Add similar authorization to listOrders, getProduct, etc.
```

### 3.2 Encryption Key Rotation Monitoring

File: `infrastructure/monitoring/monitoring_construct.py`:

```python
# Monitor KMS key rotation
kms_key_rotation_alarm = cloudwatch.Alarm(
    self,
    "KMSKeyRotationAlarm",
    metric=cloudwatch.Metric(
        namespace="AWS/KMS",
        metric_name="KeyRotationEnabled",
        statistic="Average",
        period=Duration.days(7),
        dimensions_map={
            "KeyId": self.kms_key.key_id
        }
    ),
    threshold=1,
    evaluation_periods=1,
    alarm_description="Alert if KMS key rotation is disabled"
)
```

### 3.3 Secrets Manager Rotation

```python
# File: infrastructure/stacks/ai_grocery_stack.py
# Update _create_secrets():

from aws_cdk import aws_secretsmanager as secretsmanager

# PayStack API Key with rotation
paystack_secret = secretsmanager.Secret(
    self,
    "PayStackSecret",
    secret_name=f"ai-grocery/paystack/{self.env_name}",
    description="PayStack API Key",
    # Enable automatic rotation
    generate_secret_string=secretsmanager.SecretStringValueBeta1(
        secret_string_template=json.dumps({"api_key": ""}),
        generate_string_key="api_key"
    ),
    remove_on_delete=False if self.env_name == "prod" else True
)

# Configure rotation (must be done manually for external secrets)
# In your secrets management workflow:
# 1. Update secret in AWS Secrets Manager
# 2. Lambda rotation function updates PayStack
# 3. Clients refresh from Secrets Manager
```

---

## Section 4: Verification Checklist

Before marking security as "complete," verify each item:

### API Security
- [ ] WAF deployed to AppSync
- [ ] Rate limiting: < 2000 req/5min per IP
- [ ] Request size limit: < 8KB enforced
- [ ] Input validation: All fields sanitized
- [ ] SQL injection protection: Active
- [ ] CORS properly configured
- [ ] HTTPS only (CloudFront in front of AppSync)

### Authentication & Authorization
- [ ] Cognito MFA required
- [ ] Password policy: min 12 chars, symbols required
- [ ] AppSync resolvers check authorization
- [ ] Customers can only access their own orders
- [ ] Admin scope properly gated
- [ ] Session timeout: 1 hour for access tokens
- [ ] Refresh token rotation enabled

### Data Protection
- [ ] All data encrypted at rest (KMS)
- [ ] All data encrypted in transit (TLS 1.2+)
- [ ] KMS key rotation enabled
- [ ] Database encryption verified
- [ ] Queue encryption verified
- [ ] Secrets not in logs
- [ ] Credentials rotated monthly

### Audit & Compliance
- [ ] CloudTrail enabled (all regions)
- [ ] CloudTrail logs encrypted
- [ ] CloudTrail log validation enabled
- [ ] Audit logging in Lambda functions
- [ ] Security events alert via SNS
- [ ] CloudWatch log retention: 90 days
- [ ] Sensitive logs redacted (email, payment IDs masked)

### Operational Security
- [ ] IAM roles use least privilege
- [ ] No root account API keys
- [ ] MFA required for human console access
- [ ] Emergency access procedures documented
- [ ] Key destruction procedures documented
- [ ] Incident response plan in place

---

## Testing Commands

```bash
# Test WAF rate limiting
for i in {1..2100}; do
  curl -X POST https://your-appsync-api/graphql \
    -H "Content-Type: application/json" \
    -d '{"query":"{ orders { items { orderId } } }"}' &
done
# Should receive 429 Throttled responses after 2000

# Test input validation
curl -X POST https://your-appsync-api/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query":"mutation { submitGroceryList(input: {customerEmail: \"invalid\", groceryList: \"test\"}) { orderId } }"
  }'
# Should receive validation error

# Verify CloudTrail logs
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=PutItem \
  --max-results 10

# Check KMS key rotation
aws kms get-key-rotation-status --key-id YOUR_KEY_ID
```

---

## Next Steps

Once security hardening is complete:
1. ✅ Security audit checklist (all items checked)
2. ✅ Penetration testing report (if applicable)
3. ➡️ Move to **PRIORITY 2: Resilience Patterns**
4. ➡️ Move to **PRIORITY 3: Integration Testing**

