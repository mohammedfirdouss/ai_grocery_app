"""
CDK Constructs for Amazon Bedrock Integration.

This module provides reusable CDK constructs for setting up:
- Bedrock Agents with action groups
- Bedrock Guardrails for content filtering
- Bedrock Knowledge Bases for product context
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    Fn,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_opensearchserverless as opensearchserverless,
)
from constructs import Construct
from typing import Dict, Any, Optional, List


class BedrockGuardrailConstruct(Construct):
    """
    CDK Construct for creating Bedrock Guardrails.
    
    Provides content filtering for AI responses including:
    - Hate speech filtering
    - Violence filtering
    - PII detection and masking
    - Custom topic blocking
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment: str,
        blocked_topics: Optional[List[str]] = None,
        pii_entities_to_block: Optional[List[str]] = None,
        pii_entities_to_anonymize: Optional[List[str]] = None,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.environment = environment
        
        # Default blocked topics for grocery app
        default_blocked_topics = [
            "financial-advice",
            "medical-advice",
            "legal-advice",
            "weapons",
            "drugs",
        ]
        self._blocked_topics = blocked_topics or default_blocked_topics
        
        # Default PII handling
        self._pii_to_block = pii_entities_to_block or [
            "CREDIT_DEBIT_CARD_NUMBER",
            "DRIVER_ID",
            "PASSPORT_NUMBER",
            "US_SOCIAL_SECURITY_NUMBER",
        ]
        
        self._pii_to_anonymize = pii_entities_to_anonymize or [
            "EMAIL",
            "PHONE",
            "ADDRESS",
            "NAME",
        ]
        
        # Create the guardrail
        self.guardrail = self._create_guardrail()
    
    def _create_guardrail(self) -> bedrock.CfnGuardrail:
        """Create the Bedrock Guardrail."""
        
        # Build topic policy config
        topic_policy_config = self._build_topic_policy()
        
        # Build content policy config
        content_policy_config = self._build_content_policy()
        
        # Build sensitive information policy (PII)
        sensitive_info_policy = self._build_sensitive_info_policy()
        
        # Build word policy
        word_policy_config = self._build_word_policy()
        
        guardrail = bedrock.CfnGuardrail(
            self,
            "GroceryAppGuardrail",
            name=f"ai-grocery-guardrail-{self.environment}",
            description=f"Content guardrails for AI Grocery App {self.environment} environment",
            blocked_input_messaging="I'm sorry, but I can only help with grocery shopping requests. Please provide a valid grocery list.",
            blocked_outputs_messaging="I apologize, but I'm unable to provide that type of response. Let me help you with your grocery list instead.",
            content_policy_config=content_policy_config,
            topic_policy_config=topic_policy_config,
            sensitive_information_policy_config=sensitive_info_policy,
            word_policy_config=word_policy_config,
        )
        
        return guardrail
    
    def _build_content_policy(self) -> bedrock.CfnGuardrail.ContentPolicyConfigProperty:
        """Build content policy configuration."""
        return bedrock.CfnGuardrail.ContentPolicyConfigProperty(
            filters_config=[
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type="HATE",
                    input_strength="HIGH",
                    output_strength="HIGH"
                ),
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type="INSULTS",
                    input_strength="MEDIUM",
                    output_strength="MEDIUM"
                ),
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type="SEXUAL",
                    input_strength="HIGH",
                    output_strength="HIGH"
                ),
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type="VIOLENCE",
                    input_strength="MEDIUM",
                    output_strength="MEDIUM"
                ),
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type="MISCONDUCT",
                    input_strength="HIGH",
                    output_strength="HIGH"
                ),
            ]
        )
    
    def _build_topic_policy(self) -> bedrock.CfnGuardrail.TopicPolicyConfigProperty:
        """Build topic policy configuration."""
        topics = []
        
        topic_definitions = {
            "financial-advice": "Requests for investment, stock, cryptocurrency, or financial planning advice",
            "medical-advice": "Requests for medical diagnoses, treatments, or health recommendations",
            "legal-advice": "Requests for legal counsel, interpretations, or recommendations",
            "weapons": "Requests related to weapons, ammunition, or harmful devices",
            "drugs": "Requests related to illegal drugs or controlled substances",
        }
        
        for topic in self._blocked_topics:
            if topic in topic_definitions:
                topics.append(
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name=topic.replace("-", " ").title(),
                        definition=topic_definitions[topic],
                        type="DENY",
                        examples=[
                            f"Can you give me {topic.replace('-', ' ')}?"
                        ]
                    )
                )
        
        return bedrock.CfnGuardrail.TopicPolicyConfigProperty(
            topics_config=topics
        )
    
    def _build_sensitive_info_policy(
        self
    ) -> bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty:
        """Build sensitive information policy configuration."""
        pii_entities = []
        
        # Add entities to block
        for entity in self._pii_to_block:
            pii_entities.append(
                bedrock.CfnGuardrail.PiiEntityConfigProperty(
                    type=entity,
                    action="BLOCK"
                )
            )
        
        # Add entities to anonymize
        for entity in self._pii_to_anonymize:
            pii_entities.append(
                bedrock.CfnGuardrail.PiiEntityConfigProperty(
                    type=entity,
                    action="ANONYMIZE"
                )
            )
        
        return bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
            pii_entities_config=pii_entities
        )
    
    def _build_word_policy(self) -> bedrock.CfnGuardrail.WordPolicyConfigProperty:
        """Build word policy configuration."""
        return bedrock.CfnGuardrail.WordPolicyConfigProperty(
            managed_word_lists_config=[
                bedrock.CfnGuardrail.ManagedWordsConfigProperty(
                    type="PROFANITY"
                )
            ]
        )
    
    @property
    def guardrail_id(self) -> str:
        """Get the guardrail ID."""
        return self.guardrail.attr_guardrail_id
    
    @property
    def guardrail_arn(self) -> str:
        """Get the guardrail ARN."""
        return self.guardrail.attr_guardrail_arn


class BedrockKnowledgeBaseConstruct(Construct):
    """
    CDK Construct for creating Bedrock Knowledge Base.
    
    Creates a knowledge base backed by OpenSearch Serverless
    for product catalog information retrieval.
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment: str,
        data_bucket: s3.IBucket,
        s3_prefix: str = "product-catalog/",
        embedding_model_id: str = "amazon.titan-embed-text-v1",
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.environment = environment
        self.data_bucket = data_bucket
        self.s3_prefix = s3_prefix
        self.embedding_model_id = embedding_model_id
        
        # Get account and region
        self.account = Stack.of(self).account
        self.region = Stack.of(self).region
        
        # Create IAM role for knowledge base
        self.kb_role = self._create_kb_role()
        
        # Create OpenSearch Serverless collection
        self.collection = self._create_opensearch_collection()
        
        # Create the knowledge base
        self.knowledge_base = self._create_knowledge_base()
        
        # Create data source
        self.data_source = self._create_data_source()
    
    def _create_kb_role(self) -> iam.Role:
        """Create IAM role for knowledge base."""
        role = iam.Role(
            self,
            "KnowledgeBaseRole",
            role_name=f"ai-grocery-kb-role-{self.environment}",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Role for Bedrock Knowledge Base access"
        )
        
        # Add S3 permissions
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:ListBucket",
                ],
                resources=[
                    self.data_bucket.bucket_arn,
                    f"{self.data_bucket.bucket_arn}/*"
                ]
            )
        )
        
        # Add Bedrock permissions
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{self.embedding_model_id}"
                ]
            )
        )
        
        # Add OpenSearch Serverless permissions
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:APIAccessAll",
                ],
                resources=[
                    f"arn:aws:aoss:{self.region}:{self.account}:collection/*"
                ]
            )
        )
        
        return role
    
    def _create_opensearch_collection(self) -> opensearchserverless.CfnCollection:
        """Create OpenSearch Serverless collection for vector storage."""
        collection_name = f"ai-grocery-kb-{self.environment}"
        
        # Create encryption policy
        encryption_policy = opensearchserverless.CfnSecurityPolicy(
            self,
            "EncryptionPolicy",
            name=f"ai-grocery-enc-{self.environment}",
            type="encryption",
            policy=f'''{{
                "Rules": [{{
                    "ResourceType": "collection",
                    "Resource": ["collection/{collection_name}"]
                }}],
                "AWSOwnedKey": true
            }}'''
        )
        
        # Create network policy
        network_policy = opensearchserverless.CfnSecurityPolicy(
            self,
            "NetworkPolicy",
            name=f"ai-grocery-net-{self.environment}",
            type="network",
            policy=f'''[{{
                "Rules": [{{
                    "ResourceType": "collection",
                    "Resource": ["collection/{collection_name}"]
                }},
                {{
                    "ResourceType": "dashboard",
                    "Resource": ["collection/{collection_name}"]
                }}],
                "AllowFromPublic": true
            }}]'''
        )
        
        # Create data access policy
        access_policy = opensearchserverless.CfnAccessPolicy(
            self,
            "DataAccessPolicy",
            name=f"ai-grocery-access-{self.environment}",
            type="data",
            policy=f'''[{{
                "Rules": [{{
                    "ResourceType": "collection",
                    "Resource": ["collection/{collection_name}"],
                    "Permission": ["aoss:*"]
                }},
                {{
                    "ResourceType": "index",
                    "Resource": ["index/{collection_name}/*"],
                    "Permission": ["aoss:*"]
                }}],
                "Principal": ["{self.kb_role.role_arn}"]
            }}]'''
        )
        
        # Create collection
        collection = opensearchserverless.CfnCollection(
            self,
            "VectorCollection",
            name=collection_name,
            type="VECTORSEARCH",
            description=f"Vector store for AI Grocery Knowledge Base {self.environment}"
        )
        
        # Add dependencies
        collection.add_dependency(encryption_policy)
        collection.add_dependency(network_policy)
        collection.add_dependency(access_policy)
        
        return collection
    
    def _create_knowledge_base(self) -> bedrock.CfnKnowledgeBase:
        """Create the Bedrock Knowledge Base."""
        return bedrock.CfnKnowledgeBase(
            self,
            "ProductKnowledgeBase",
            name=f"ai-grocery-products-kb-{self.environment}",
            description=f"Product catalog knowledge base for AI Grocery App {self.environment}",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/{self.embedding_model_id}"
                )
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=self.collection.attr_arn,
                    vector_index_name="bedrock-knowledge-base-default-index",
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        vector_field="bedrock-knowledge-base-default-vector",
                        text_field="AMAZON_BEDROCK_TEXT_CHUNK",
                        metadata_field="AMAZON_BEDROCK_METADATA"
                    )
                )
            )
        )
    
    def _create_data_source(self) -> bedrock.CfnDataSource:
        """Create data source for the knowledge base."""
        return bedrock.CfnDataSource(
            self,
            "ProductDataSource",
            name=f"ai-grocery-products-{self.environment}",
            description="Product catalog data from S3",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=self.data_bucket.bucket_arn,
                    inclusion_prefixes=[self.s3_prefix]
                )
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=512,
                        overlap_percentage=20
                    )
                )
            )
        )
    
    @property
    def knowledge_base_id(self) -> str:
        """Get the knowledge base ID."""
        return self.knowledge_base.attr_knowledge_base_id
    
    @property
    def knowledge_base_arn(self) -> str:
        """Get the knowledge base ARN."""
        return self.knowledge_base.attr_knowledge_base_arn


class BedrockAgentConstruct(Construct):
    """
    CDK Construct for creating Bedrock Agent.
    
    Creates a Bedrock Agent configured for grocery list processing
    with optional knowledge base and guardrail integration.
    """
    
    AGENT_INSTRUCTION = """You are an AI-powered grocery list processing agent for a shopping application. Your primary function is to help users convert their natural language grocery lists into structured, actionable shopping orders.

Core Responsibilities:
1. Parse and understand grocery lists in various formats (bullet points, numbered lists, free-form text)
2. Extract individual grocery items with normalized product names, quantities, and units
3. Provide confidence scores for each extraction
4. Flag uncertain extractions for review

Constraints:
- Only process grocery and household shopping related requests
- Do not provide medical, financial, or legal advice
- Always respond with properly formatted JSON for structured outputs
- If unable to process a request, explain why clearly"""
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment: str,
        foundation_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
        guardrail: Optional[BedrockGuardrailConstruct] = None,
        knowledge_base: Optional[BedrockKnowledgeBaseConstruct] = None,
        lambda_function: Optional[lambda_.IFunction] = None,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.environment = environment
        self.foundation_model_id = foundation_model_id
        self.guardrail = guardrail
        self.knowledge_base = knowledge_base
        self.lambda_function = lambda_function
        
        # Get account and region
        self.account = Stack.of(self).account
        self.region = Stack.of(self).region
        
        # Create agent role
        self.agent_role = self._create_agent_role()
        
        # Create the agent
        self.agent = self._create_agent()
        
        # Create agent alias for versioning
        self.agent_alias = self._create_agent_alias()
    
    def _create_agent_role(self) -> iam.Role:
        """Create IAM role for the Bedrock Agent."""
        role = iam.Role(
            self,
            "AgentRole",
            role_name=f"ai-grocery-agent-role-{self.environment}",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Role for AI Grocery Bedrock Agent"
        )
        
        # Add Bedrock model permissions
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{self.foundation_model_id}"
                ]
            )
        )
        
        # Add knowledge base permissions if configured
        if self.knowledge_base:
            role.add_to_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "bedrock:Retrieve",
                        "bedrock:RetrieveAndGenerate",
                    ],
                    resources=[
                        self.knowledge_base.knowledge_base_arn
                    ]
                )
            )
        
        # Add Lambda permissions if configured
        if self.lambda_function:
            role.add_to_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "lambda:InvokeFunction",
                    ],
                    resources=[
                        self.lambda_function.function_arn
                    ]
                )
            )
        
        return role
    
    def _create_agent(self) -> bedrock.CfnAgent:
        """Create the Bedrock Agent."""
        agent_config: Dict[str, Any] = {
            "agent_name": f"ai-grocery-agent-{self.environment}",
            "description": f"AI Grocery List Processing Agent for {self.environment}",
            "agent_resource_role_arn": self.agent_role.role_arn,
            "foundation_model": self.foundation_model_id,
            "instruction": self.AGENT_INSTRUCTION,
            "idle_session_ttl_in_seconds": 600,
            "auto_prepare": True,
        }
        
        # Add guardrail configuration if provided
        if self.guardrail:
            agent_config["guardrail_configuration"] = bedrock.CfnAgent.GuardrailConfigurationProperty(
                guardrail_identifier=self.guardrail.guardrail_id,
                guardrail_version="DRAFT"
            )
        
        # Add prompt override configuration for better control
        agent_config["prompt_override_configuration"] = bedrock.CfnAgent.PromptOverrideConfigurationProperty(
            prompt_configurations=[
                bedrock.CfnAgent.PromptConfigurationProperty(
                    prompt_type="PRE_PROCESSING",
                    inference_configuration=bedrock.CfnAgent.InferenceConfigurationProperty(
                        temperature=0.0,
                        top_p=1.0,
                        maximum_length=2048,
                    ),
                    prompt_creation_mode="DEFAULT",
                    prompt_state="ENABLED"
                ),
                bedrock.CfnAgent.PromptConfigurationProperty(
                    prompt_type="ORCHESTRATION",
                    inference_configuration=bedrock.CfnAgent.InferenceConfigurationProperty(
                        temperature=0.1,
                        top_p=0.9,
                        maximum_length=4096,
                    ),
                    prompt_creation_mode="DEFAULT",
                    prompt_state="ENABLED"
                )
            ]
        )
        
        agent = bedrock.CfnAgent(
            self,
            "GroceryProcessingAgent",
            **agent_config
        )
        
        # Associate knowledge base if provided
        if self.knowledge_base:
            bedrock.CfnAgentKnowledgeBaseAssociation(
                self,
                "KnowledgeBaseAssociation",
                agent_id=agent.attr_agent_id,
                agent_version="DRAFT",
                knowledge_base_id=self.knowledge_base.knowledge_base_id,
                description="Product catalog knowledge base for context",
                knowledge_base_state="ENABLED"
            )
        
        return agent
    
    def _create_agent_alias(self) -> bedrock.CfnAgentAlias:
        """Create agent alias for versioning."""
        return bedrock.CfnAgentAlias(
            self,
            "AgentAlias",
            agent_alias_name=f"ai-grocery-agent-{self.environment}-live",
            agent_id=self.agent.attr_agent_id,
            description=f"Live alias for AI Grocery Agent {self.environment}"
        )
    
    @property
    def agent_id(self) -> str:
        """Get the agent ID."""
        return self.agent.attr_agent_id
    
    @property
    def agent_arn(self) -> str:
        """Get the agent ARN."""
        return self.agent.attr_agent_arn
    
    @property
    def agent_alias_id(self) -> str:
        """Get the agent alias ID."""
        return self.agent_alias.attr_agent_alias_id
