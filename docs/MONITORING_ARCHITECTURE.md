# Monitoring Architecture

This document provides a visual overview of the monitoring and observability architecture for the AI Grocery App.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AI Grocery App Monitoring Architecture                │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                              Application Layer                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Text Parser │  │   Product    │  │   Payment    │  │    Event     │   │
│  │    Lambda    │  │   Matcher    │  │  Processor   │  │   Handler    │   │
│  │              │  │    Lambda    │  │    Lambda    │  │    Lambda    │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                  │                  │            │
│         └─────────────────┴──────────────────┴──────────────────┘            │
│                                    │                                          │
│                          ┌─────────▼─────────┐                               │
│                          │  Payment Webhook  │                               │
│                          │      Lambda       │                               │
│                          └───────────────────┘                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Logs, Metrics, Traces
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────┐
│                          Observability Layer                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                     AWS Lambda Powertools                          │     │
│  ├────────────────────────────────────────────────────────────────────┤     │
│  │  • Logger (Structured JSON Logs)                                  │     │
│  │  • Tracer (X-Ray Distributed Tracing)                             │     │
│  │  • Metrics (Custom CloudWatch Metrics)                            │     │
│  └──────────┬─────────────────────────────┬────────────────┬─────────┘     │
│             │                             │                │                │
│             ▼                             ▼                ▼                │
│  ┌──────────────────┐         ┌──────────────────┐  ┌──────────────┐      │
│  │  CloudWatch Logs │         │  CloudWatch       │  │   AWS X-Ray  │      │
│  │                  │         │  Metrics          │  │              │      │
│  │  • Text Parser   │         │                   │  │  • Service   │      │
│  │  • Product Match │         │  • Lambda Metrics │  │    Map       │      │
│  │  • Payment Proc  │         │  • SQS Metrics    │  │  • Traces    │      │
│  │  • Payment Hook  │         │  • DynamoDB       │  │  • Latency   │      │
│  │  • Event Handler │         │  • Custom App     │  │  • Errors    │      │
│  │  • Health Check  │         │    Metrics        │  │              │      │
│  └──────────────────┘         └──────────────────┘  └──────────────┘      │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Alerts & Dashboards
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────┐
│                          Monitoring & Alerting                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │                    CloudWatch Alarms                              │       │
│  ├──────────────────────────────────────────────────────────────────┤       │
│  │  Lambda Alarms:                                                  │       │
│  │    • Error Rate (5+ in 10 min)                                   │       │
│  │    • Latency (p90 > 80% timeout)                                 │       │
│  │    • Throttling (>= 1 event)                                     │       │
│  │                                                                   │       │
│  │  SQS Alarms:                                                     │       │
│  │    • DLQ Messages (>= 1)                                         │       │
│  │    • Message Age (> 1 hour)                                      │       │
│  │                                                                   │       │
│  │  DynamoDB Alarms:                                                │       │
│  │    • Read Throttling (>= 1)                                      │       │
│  │    • Write Throttling (>= 1)                                     │       │
│  │    • System Errors (>= 1)                                        │       │
│  └─────────────────────────────┬────────────────────────────────────┘       │
│                                │                                             │
│                                ▼                                             │
│                    ┌────────────────────────┐                               │
│                    │     SNS Alarm Topic    │                               │
│                    │  ai-grocery-alarms-*   │                               │
│                    └───────────┬────────────┘                               │
│                                │                                             │
│                    ┌───────────▼────────────┐                               │
│                    │  Email Notifications   │                               │
│                    │  (Optional)            │                               │
│                    └────────────────────────┘                               │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │                  CloudWatch Dashboard                             │       │
│  │              ai-grocery-{env}-dashboard                           │       │
│  ├──────────────────────────────────────────────────────────────────┤       │
│  │  • Lambda Invocations, Errors, Duration                          │       │
│  │  • SQS Queue Depth, Message Age                                  │       │
│  │  • DynamoDB Read/Write Capacity                                  │       │
│  │  • Custom Application Metrics                                    │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │                       AWS Budgets                                 │       │
│  │            ai-grocery-{env}-monthly-budget                        │       │
│  ├──────────────────────────────────────────────────────────────────┤       │
│  │  • 80% Actual Threshold                                          │       │
│  │  • 100% Forecasted Threshold                                     │       │
│  │  • SNS/Email Notifications                                       │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                          Health Check System                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌────────────────────────────┐                                             │
│  │  EventBridge Scheduled Rule │                                             │
│  │     (Every 5 minutes)       │                                             │
│  └─────────────┬───────────────┘                                             │
│                │                                                              │
│                ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────┐           │
│  │              Health Check Lambda                              │           │
│  ├──────────────────────────────────────────────────────────────┤           │
│  │  Checks:                                                     │           │
│  │    • DynamoDB Tables (status, item count)                    │           │
│  │    • SQS Queues (messages, accessibility)                    │           │
│  │    • Lambda Functions (state, config)                        │           │
│  │                                                               │           │
│  │  Emits:                                                      │           │
│  │    • HealthCheckStatus metric (1=healthy, 0=unhealthy)      │           │
│  │    • JSON structured logs                                    │           │
│  │    • X-Ray traces                                            │           │
│  └──────────────────────────────────────────────────────────────┘           │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Custom Metrics Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Processing Stage Metrics                            │
└─────────────────────────────────────────────────────────────────────────────┘

User Request
     │
     ▼
┌─────────────────┐
│  Text Parser    │  Emits Metrics:
│     Lambda      │  • TextParsingSuccess/Error
└────────┬────────┘  • TextValidationError
         │           • OrderStatusUpdateSuccess/Failure
         │           • ProductMatcherQueueSendSuccess/Failure
         │
         ▼
┌─────────────────┐
│ Product Matcher │  Emits Metrics:
│     Lambda      │  • BedrockInvocationSuccess/Error
└────────┬────────┘  • ItemsExtracted/Matched/Unmatched
         │           • MatchConfidence
         │           • GuardrailBlocked, RateLimitHit
         │
         ▼
┌─────────────────┐
│Payment Processor│  Emits Metrics:
│     Lambda      │  • PaymentLinkCreated
└────────┬────────┘  • PaymentLinkError
         │           • PaymentAmount
         │
         ▼
┌─────────────────┐
│ Payment Webhook │  Emits Metrics:
│     Lambda      │  • WebhookReceived
└────────┬────────┘  • PaymentSuccess/Failed
         │           • WebhookInvalidSignature
         │           • TransferSuccess
         │
         ▼
┌─────────────────┐
│ Event Handler   │  Emits Metrics:
│     Lambda      │  • OrderUpdateNotificationPublished/Failed
└─────────────────┘  • DynamoDBStreamEventsProcessed

         All metrics flow to:
                │
                ▼
        CloudWatch Metrics
     Namespace: AiGroceryApp/{env}
```

## Monitoring Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                     Application Events                            │
└──────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐   ┌──────────┐
        │   Logs   │    │ Metrics  │   │  Traces  │
        └─────┬────┘    └─────┬────┘   └─────┬────┘
              │               │              │
              ▼               ▼              ▼
      CloudWatch       CloudWatch        AWS X-Ray
         Logs           Metrics
              │               │              │
              └───────────────┼──────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   Visualization  │
                    ├──────────────────┤
                    │  • Dashboards    │
                    │  • Alarms        │
                    │  • Insights      │
                    │  • Service Maps  │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Notifications   │
                    ├──────────────────┤
                    │  • SNS Topic     │
                    │  • Email         │
                    │  • Budget Alerts │
                    └──────────────────┘
```

## Alarm Severity Levels

```
┌─────────────────────────────────────────────────────────────────┐
│                      Alarm Priority Matrix                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CRITICAL (Immediate Action Required):                          │
│    • Lambda Error Rate > 5 in 10 minutes                       │
│    • DLQ Messages Present                                       │
│    • DynamoDB System Errors                                     │
│    • Budget > 100% (Forecasted)                                 │
│                                                                  │
│  HIGH (Action Required Soon):                                   │
│    • Lambda Throttling                                          │
│    • DynamoDB Read/Write Throttling                             │
│    • SQS Message Age > 1 hour                                   │
│    • Budget > 80% (Actual)                                      │
│                                                                  │
│  MEDIUM (Investigation Needed):                                 │
│    • Lambda Latency p90 > 80% timeout                          │
│    • Health Check Status = 0                                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Environment-Specific Configuration

```
┌───────────────────────────────────────────────────────────────────┐
│                Environment Configuration Matrix                    │
├───────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Setting              │  Dev      │  Staging   │  Production      │
│  ─────────────────────┼───────────┼────────────┼─────────────────│
│  X-Ray Tracing        │  Enabled  │  Enabled   │  Enabled         │
│  Log Retention        │  7 days   │  30 days   │  90 days         │
│  Monthly Budget       │  $50      │  $200      │  $1000           │
│  Alarm Email          │  None     │  Optional  │  Required        │
│  Health Check Freq    │  5 min    │  5 min     │  5 min           │
│  Dashboard            │  Full     │  Full      │  Essential       │
│                                                                    │
└───────────────────────────────────────────────────────────────────┘
```

## Integration Points

```
┌──────────────────────────────────────────────────────────────────────┐
│                    External Service Integration                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Application                                                         │
│       │                                                              │
│       ├─► DynamoDB Tables ──► CloudWatch Metrics ──► Alarms         │
│       │                                                              │
│       ├─► SQS Queues ──────► CloudWatch Metrics ──► Alarms         │
│       │                                                              │
│       ├─► Lambda Functions ─► CloudWatch Logs ────► Log Insights   │
│       │                   └─► CloudWatch Metrics ──► Dashboard      │
│       │                   └─► X-Ray Traces ────────► Service Map    │
│       │                                                              │
│       └─► AppSync API ─────► CloudWatch Logs                        │
│                           └─► X-Ray Traces                          │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

## Troubleshooting Flow

```
┌────────────────────────────────────────────────────────────────┐
│                  Incident Response Flow                         │
└────────────────────────────────────────────────────────────────┘

      Alarm Triggered
            │
            ▼
   ┌─────────────────┐
   │  Check Dashboard│ ──► Identify affected component
   └────────┬────────┘
            │
            ▼
   ┌─────────────────┐
   │  Review Logs    │ ──► CloudWatch Logs Insights
   └────────┬────────┘     • Error messages
            │              • Stack traces
            │              • Correlation IDs
            ▼
   ┌─────────────────┐
   │ Analyze Traces  │ ──► X-Ray Service Map
   └────────┬────────┘     • Request path
            │              • Latency breakdown
            │              • Error locations
            ▼
   ┌─────────────────┐
   │  Check Metrics  │ ──► Custom Application Metrics
   └────────┬────────┘     • Processing stage status
            │              • Success/failure rates
            │
            ▼
   ┌─────────────────┐
   │ Health Check    │ ──► Component health status
   └────────┬────────┘     • DynamoDB status
            │              • SQS accessibility
            │              • Lambda states
            ▼
      Root Cause
      Identified
            │
            ▼
      Fix & Verify
            │
            ▼
   Post-Incident Review
```

## Key Features Summary

✅ **Real-time Monitoring**: Immediate visibility into system health
✅ **Comprehensive Metrics**: All processing stages tracked
✅ **Proactive Alerting**: Issues detected before user impact
✅ **Cost Control**: Budget alerts prevent overspending
✅ **Health Checks**: Automated dependency monitoring
✅ **Distributed Tracing**: End-to-end request correlation
✅ **Structured Logging**: Consistent, queryable logs
✅ **Least Privilege**: Secure IAM permissions
✅ **Multi-Environment**: Configuration per environment
✅ **Documentation**: Complete operational guides

## Next Steps

1. **Tune Alarm Thresholds**: Adjust based on actual traffic patterns
2. **Review Dashboard**: Customize widgets for team needs
3. **Set Up Alerts**: Configure email recipients per environment
4. **Enable Notifications**: Connect SNS to Slack/PagerDuty
5. **Create Runbooks**: Document common incident scenarios
6. **Schedule Reviews**: Weekly monitoring health checks
7. **Cost Optimization**: Monitor and optimize based on budget alerts
