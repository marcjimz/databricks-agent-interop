# Databricks notebook source
# MAGIC %md
# MAGIC # Agent Traces SDP — Medallion Pipeline
# MAGIC
# MAGIC Multi-source agent trace ingestion with Delta Live Tables (DLT).
# MAGIC
# MAGIC **Bronze:** Raw traces from 4 sources (Foundry real, 3 stubs)
# MAGIC **Silver:** Normalized OTEL spans (consistent schema)
# MAGIC **Gold:** Aggregated conversations ready for MLflow upload
# MAGIC
# MAGIC ```
# MAGIC foundry_traces_raw ──────→ foundry_spans ──────────┐
# MAGIC salesforce_traces_raw ───→ salesforce_spans ────────┤
# MAGIC copilot_studio_traces_raw → copilot_studio_spans ──┤→ all_spans → agent_conversations → mlflow_trace_uploads
# MAGIC servicenow_traces_raw ───→ servicenow_spans ───────┘
# MAGIC ```

# COMMAND ----------

import dlt
import json
from pyspark.sql.functions import (
    col, lit, current_timestamp, from_json, to_json,
    collect_list, struct, coalesce, expr, concat_ws,
    sum as spark_sum, count, min as spark_min, max as spark_max,
    first, when, udf, array, monotonically_increasing_id
)
from pyspark.sql.types import (
    StructType, StructField, StringType, LongType, BooleanType,
    DoubleType, TimestampType, ArrayType, MapType, IntegerType
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# Pipeline configuration (passed from databricks.yml → spark.conf)
catalog = spark.conf.get("catalog")
prefix = spark.conf.get("prefix")
subscription_id = spark.conf.get("subscription_id")
resource_group = spark.conf.get("resource_group")

# Derive storage account from prefix (matches Terraform naming: st{prefix}uc)
storage_account = f"st{prefix.replace('-', '')}uc"
container_name = "insights-logs-appdependencies"

# Build ABFSS path for AutoLoader (UC external location provides auth)
appi_name = f"appi-{prefix}"
resource_id_prefix = (
    f"resourceId=/SUBSCRIPTIONS/{subscription_id.upper()}"
    f"/RESOURCEGROUPS/{resource_group.upper()}"
    f"/PROVIDERS/MICROSOFT.INSIGHTS"
    f"/COMPONENTS/{appi_name.upper()}"
)
landing_path = f"abfss://{container_name}@{storage_account}.dfs.core.windows.net/{resource_id_prefix}"
checkpoint_path = "/tmp/agent_traces_autoloader_checkpoint"

print(f"Storage Account: {storage_account}")
print(f"Landing Path:    {landing_path[:80]}...")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze Layer — Raw Trace Ingestion

# COMMAND ----------

# MAGIC %md
# MAGIC ### Foundry Traces (Real — AutoLoader Streaming)

# COMMAND ----------

@dlt.table(
    name="foundry_traces_raw",
    comment="Raw Azure AI Foundry agent traces from App Insights NDJSON exports",
    table_properties={
        "quality": "bronze",
        "pipelines.autoOptimize.zOrderCols": "ingested_at",
    },
)
def foundry_traces_raw():
    """Bronze streaming table: Raw Foundry traces via AutoLoader from blob storage."""
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.schemaLocation", checkpoint_path)
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.partitionColumns", "")
        .option("pathGlobFilter", "*.json")
        .load(landing_path)
        .select(
            col("*"),
            lit("foundry").alias("source_system"),
            current_timestamp().alias("ingested_at"),
        )
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ### Salesforce Einstein Copilot (Stub)

# COMMAND ----------

@dlt.table(
    name="salesforce_traces_raw",
    comment="[STUB] Salesforce Einstein Copilot traces — EventLogFile format",
    table_properties={"quality": "bronze"},
)
def salesforce_traces_raw():
    """Bronze batch table: Simulated Salesforce Einstein Copilot traces."""
    data = [
        {
            "EventType": "EinsteinCopilotTurn",
            "SessionKey": "sf-session-001",
            "CreatedDate": "2025-02-15T10:30:00.000Z",
            "UserId": "005xx000001X8VQ",
            "UserName": "user@company.com",
            "ConversationId": "sf-conv-001",
            "TurnNumber": "1",
            "UserQuery": "What are my top opportunities this quarter?",
            "AssistantResponse": "Here are your top 5 opportunities for Q1: 1) Acme Corp ($50K), 2) Globex ($35K), 3) Initech ($28K)...",
            "ActionName": "query_opportunities",
            "ActionResult": '{"opportunities": [{"name": "Acme Corp", "amount": 50000}, {"name": "Globex", "amount": 35000}]}',
            "ModelName": "gpt-4o",
            "InputTokens": "120",
            "OutputTokens": "280",
            "DurationMs": "1450",
            "Status": "Success",
            "source_system": "salesforce",
        },
        {
            "EventType": "EinsteinCopilotTurn",
            "SessionKey": "sf-session-001",
            "CreatedDate": "2025-02-15T10:30:05.000Z",
            "UserId": "005xx000001X8VQ",
            "UserName": "user@company.com",
            "ConversationId": "sf-conv-001",
            "TurnNumber": "2",
            "UserQuery": "Tell me more about Acme Corp",
            "AssistantResponse": "Acme Corp is in the Negotiation stage with expected close date March 15. Key contact: Jane Doe, VP of Engineering.",
            "ActionName": "get_opportunity_detail",
            "ActionResult": '{"name": "Acme Corp", "stage": "Negotiation", "close_date": "2025-03-15", "contact": "Jane Doe"}',
            "ModelName": "gpt-4o",
            "InputTokens": "95",
            "OutputTokens": "150",
            "DurationMs": "1200",
            "Status": "Success",
            "source_system": "salesforce",
        },
        {
            "EventType": "EinsteinCopilotTurn",
            "SessionKey": "sf-session-002",
            "CreatedDate": "2025-02-15T11:00:00.000Z",
            "UserId": "005xx000001X8VR",
            "UserName": "manager@company.com",
            "ConversationId": "sf-conv-002",
            "TurnNumber": "1",
            "UserQuery": "Summarize my team's pipeline for this month",
            "AssistantResponse": "Your team's pipeline for February: Total value $425K across 12 opportunities. 3 are in Closed Won ($87K), 5 in Negotiation ($210K).",
            "ActionName": "pipeline_summary",
            "ActionResult": '{"total": 425000, "count": 12, "closed_won": 87000}',
            "ModelName": "gpt-4o",
            "InputTokens": "85",
            "OutputTokens": "200",
            "DurationMs": "1800",
            "Status": "Success",
            "source_system": "salesforce",
        },
    ]
    return spark.createDataFrame(data)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Copilot Studio / Dataverse (Stub)

# COMMAND ----------

@dlt.table(
    name="copilot_studio_traces_raw",
    comment="[STUB] Microsoft Copilot Studio traces — Dataverse transcript format",
    table_properties={"quality": "bronze"},
)
def copilot_studio_traces_raw():
    """Bronze batch table: Simulated Copilot Studio conversation transcripts."""
    data = [
        {
            "conversationid": "cs-conv-001",
            "createdon": "2025-02-15T11:00:00.000Z",
            "botid": "bot-hr-assistant",
            "botname": "HR Benefits Bot",
            "content": json.dumps(
                {
                    "activities": [
                        {
                            "type": "message",
                            "from": {"role": "user"},
                            "text": "How many vacation days do I have left?",
                            "timestamp": "2025-02-15T11:00:01.000Z",
                        },
                        {
                            "type": "message",
                            "from": {"role": "bot"},
                            "text": "You have 12 vacation days remaining for 2025. Would you like to submit a time-off request?",
                            "timestamp": "2025-02-15T11:00:03.500Z",
                        },
                    ]
                }
            ),
            "schemaversion": "1.0",
            "channelid": "msteams",
            "DurationMs": "2500",
            "source_system": "copilot_studio",
        },
        {
            "conversationid": "cs-conv-002",
            "createdon": "2025-02-15T14:30:00.000Z",
            "botid": "bot-it-helpdesk",
            "botname": "IT Helpdesk Bot",
            "content": json.dumps(
                {
                    "activities": [
                        {
                            "type": "message",
                            "from": {"role": "user"},
                            "text": "My laptop screen is flickering",
                            "timestamp": "2025-02-15T14:30:01.000Z",
                        },
                        {
                            "type": "message",
                            "from": {"role": "bot"},
                            "text": "I'm sorry to hear that. Let me create a support ticket for you. Can you provide your asset tag number?",
                            "timestamp": "2025-02-15T14:30:03.000Z",
                        },
                        {
                            "type": "message",
                            "from": {"role": "user"},
                            "text": "It's ASSET-2024-5567",
                            "timestamp": "2025-02-15T14:30:15.000Z",
                        },
                        {
                            "type": "message",
                            "from": {"role": "bot"},
                            "text": "I've created ticket INC0045678 for you. A technician will reach out within 4 hours.",
                            "timestamp": "2025-02-15T14:30:17.000Z",
                        },
                    ]
                }
            ),
            "schemaversion": "1.0",
            "channelid": "webchat",
            "DurationMs": "17000",
            "source_system": "copilot_studio",
        },
    ]
    return spark.createDataFrame(data)

# COMMAND ----------

# MAGIC %md
# MAGIC ### ServiceNow Virtual Agent (Stub)

# COMMAND ----------

@dlt.table(
    name="servicenow_traces_raw",
    comment="[STUB] ServiceNow Virtual Agent traces — sys_cs_conversation format",
    table_properties={"quality": "bronze"},
)
def servicenow_traces_raw():
    """Bronze batch table: Simulated ServiceNow Virtual Agent conversations."""
    data = [
        {
            "sys_id": "sn-conv-001",
            "opened_at": "2025-02-15T12:00:00.000Z",
            "closed_at": "2025-02-15T12:01:00.000Z",
            "virtual_agent_topic": "Password Reset",
            "channel": "web_chat",
            "user_sys_id": "user-sn-001",
            "user_name": "jsmith",
            "messages": json.dumps(
                [
                    {
                        "role": "user",
                        "text": "I need to reset my VPN password",
                        "timestamp": "2025-02-15T12:00:01.000Z",
                    },
                    {
                        "role": "bot",
                        "text": "I can help you reset your VPN password. Let me verify your identity first. What is your employee ID?",
                        "timestamp": "2025-02-15T12:00:02.500Z",
                        "topic_action": "identity_verification",
                    },
                    {
                        "role": "user",
                        "text": "EMP12345",
                        "timestamp": "2025-02-15T12:00:30.000Z",
                    },
                    {
                        "role": "bot",
                        "text": "Identity verified. Your VPN password has been reset. A temporary password has been sent to your email.",
                        "timestamp": "2025-02-15T12:01:00.000Z",
                        "topic_action": "password_reset",
                    },
                ]
            ),
            "resolution_code": "Resolved",
            "DurationMs": "60000",
            "source_system": "servicenow",
        },
        {
            "sys_id": "sn-conv-002",
            "opened_at": "2025-02-15T13:15:00.000Z",
            "closed_at": "2025-02-15T13:18:00.000Z",
            "virtual_agent_topic": "Software Request",
            "channel": "slack",
            "user_sys_id": "user-sn-002",
            "user_name": "mjones",
            "messages": json.dumps(
                [
                    {
                        "role": "user",
                        "text": "I need access to Tableau Desktop",
                        "timestamp": "2025-02-15T13:15:01.000Z",
                    },
                    {
                        "role": "bot",
                        "text": "I can submit a software request for Tableau Desktop. This requires manager approval. Shall I proceed?",
                        "timestamp": "2025-02-15T13:15:03.000Z",
                        "topic_action": "catalog_lookup",
                    },
                    {
                        "role": "user",
                        "text": "Yes please",
                        "timestamp": "2025-02-15T13:16:00.000Z",
                    },
                    {
                        "role": "bot",
                        "text": "Request REQ0078901 submitted. Your manager will receive an approval email. Typical turnaround is 1-2 business days.",
                        "timestamp": "2025-02-15T13:16:02.000Z",
                        "topic_action": "submit_request",
                    },
                ]
            ),
            "resolution_code": "Resolved",
            "DurationMs": "180000",
            "source_system": "servicenow",
        },
    ]
    return spark.createDataFrame(data)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver Layer — Normalized OTEL Spans
# MAGIC
# MAGIC All silver tables produce a consistent schema:
# MAGIC `trace_id, span_id, operation_name, span_type, start/end_time_ms, status, source_system, agent_id, conversation_id, model, messages, tokens, attributes`

# COMMAND ----------

# MAGIC %md
# MAGIC ### Helper Functions

# COMMAND ----------

def iso_to_epoch_ms(iso_str):
    """Convert ISO 8601 timestamp to milliseconds since epoch."""
    if not iso_str:
        return None
    from datetime import datetime
    try:
        if "." in iso_str:
            base, frac = iso_str.split(".")
            frac = frac.rstrip("Z")[:6]
            iso_str = f"{base}.{frac}+00:00"
        else:
            iso_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def map_span_type_foundry(span_type, op_name):
    """Map App Insights span_type + operation to OTEL span type."""
    if span_type == "tool" or op_name == "execute_tool":
        return "TOOL"
    if span_type == "agent" and op_name == "chat":
        return "CHAT_MODEL"
    return "CHAIN"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Foundry Spans (Real Transformation)

# COMMAND ----------

# Normalized span schema shared across all silver tables
SPAN_SCHEMA = StructType([
    StructField("trace_id", StringType(), False),
    StructField("span_id", StringType(), True),
    StructField("operation_name", StringType(), True),
    StructField("span_type", StringType(), True),
    StructField("start_time_ms", LongType(), True),
    StructField("end_time_ms", LongType(), True),
    StructField("duration_ms", LongType(), True),
    StructField("status", StringType(), True),
    StructField("source_system", StringType(), False),
    StructField("agent_id", StringType(), True),
    StructField("conversation_id", StringType(), True),
    StructField("model", StringType(), True),
    StructField("input_messages", StringType(), True),
    StructField("output_messages", StringType(), True),
    StructField("tool_name", StringType(), True),
    StructField("tool_result", StringType(), True),
    StructField("input_tokens", IntegerType(), True),
    StructField("output_tokens", IntegerType(), True),
    StructField("attributes", StringType(), True),
])


@udf(returnType=SPAN_SCHEMA)
def transform_foundry_span(time_val, name, span_id, op_id, duration_ms, success,
                           properties, measurements):
    """Transform a Foundry App Insights record into a normalized OTEL span."""
    # Properties/Measurements arrive as Row objects (StructType), not dicts
    props = properties.asDict() if properties else {}
    meas = measurements.asDict() if measurements else {}

    span_type_raw = props.get("span_type", "")
    op_name = props.get("gen_ai.operation.name", "")

    start_ms = iso_to_epoch_ms(time_val)
    dur = int(duration_ms) if duration_ms else 0
    end_ms = (start_ms + dur) if start_ms else None

    # Token extraction (Measurements numeric → Properties string fallback)
    input_tok = None
    output_tok = None
    if meas.get("gen_ai.usage.input_tokens") is not None:
        input_tok = int(meas["gen_ai.usage.input_tokens"])
    elif props.get("gen_ai.usage.input_tokens"):
        input_tok = int(float(props["gen_ai.usage.input_tokens"]))
    if meas.get("gen_ai.usage.output_tokens") is not None:
        output_tok = int(meas["gen_ai.usage.output_tokens"])
    elif props.get("gen_ai.usage.output_tokens"):
        output_tok = int(float(props["gen_ai.usage.output_tokens"]))

    # Extra attributes
    extra_attrs = {}
    for key in ["gen_ai.request.model", "gen_ai.response.model", "gen_ai.tool.type",
                "gen_ai.agent.id", "gen_ai.conversation.id"]:
        if props.get(key):
            extra_attrs[key] = props[key]

    return (
        op_id,
        span_id,
        f"{op_name} {name}" if op_name else name,
        map_span_type_foundry(span_type_raw, op_name),
        start_ms,
        end_ms,
        dur,
        "OK" if success else "ERROR",
        "foundry",
        props.get("gen_ai.agent.id"),
        props.get("gen_ai.conversation.id"),
        props.get("gen_ai.request.model"),
        props.get("gen_ai.input.messages"),
        props.get("gen_ai.output.messages"),
        props.get("gen_ai.tool.name"),
        props.get("gen_ai.tool.call.result"),
        input_tok,
        output_tok,
        json.dumps(extra_attrs) if extra_attrs else None,
    )


@dlt.table(
    name="foundry_spans",
    comment="Normalized OTEL spans from Azure AI Foundry agent traces",
    table_properties={
        "quality": "silver",
        "pipelines.autoOptimize.zOrderCols": "trace_id,start_time_ms",
    },
)
@dlt.expect_or_drop("valid_trace_id", "trace_id IS NOT NULL")
def foundry_spans():
    """Silver streaming table: Foundry traces normalized to OTEL span schema."""
    raw = dlt.read_stream("foundry_traces_raw")
    return raw.withColumn(
        "span",
        transform_foundry_span(
            col("time"), col("Name"), col("Id"), col("OperationId"),
            col("DurationMs"), col("Success"), col("Properties"), col("Measurements"),
        ),
    ).select("span.*")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Salesforce Spans (Stub)

# COMMAND ----------

@dlt.table(
    name="salesforce_spans",
    comment="[STUB] Normalized spans from Salesforce Einstein Copilot",
    table_properties={"quality": "silver"},
)
def salesforce_spans():
    """Silver batch table: Stub Salesforce spans normalized to OTEL schema."""
    raw = dlt.read("salesforce_traces_raw")
    return raw.select(
        col("ConversationId").alias("trace_id"),
        concat_ws("-", lit("sf"), col("SessionKey"), col("TurnNumber")).alias("span_id"),
        coalesce(col("ActionName"), lit("chat")).alias("operation_name"),
        when(col("ActionName").isNotNull(), lit("TOOL")).otherwise(lit("CHAT_MODEL")).alias("span_type"),
        expr(f"CAST(NULL AS BIGINT)").alias("start_time_ms"),
        expr(f"CAST(NULL AS BIGINT)").alias("end_time_ms"),
        col("DurationMs").cast("long").alias("duration_ms"),
        when(col("Status") == "Success", lit("OK")).otherwise(lit("ERROR")).alias("status"),
        lit("salesforce").alias("source_system"),
        lit("einstein-copilot").alias("agent_id"),
        col("ConversationId").alias("conversation_id"),
        col("ModelName").alias("model"),
        col("UserQuery").alias("input_messages"),
        col("AssistantResponse").alias("output_messages"),
        col("ActionName").alias("tool_name"),
        col("ActionResult").alias("tool_result"),
        col("InputTokens").cast("int").alias("input_tokens"),
        col("OutputTokens").cast("int").alias("output_tokens"),
        lit(None).cast("string").alias("attributes"),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ### Copilot Studio Spans (Stub)

# COMMAND ----------

@dlt.table(
    name="copilot_studio_spans",
    comment="[STUB] Normalized spans from Microsoft Copilot Studio",
    table_properties={"quality": "silver"},
)
def copilot_studio_spans():
    """Silver batch table: Stub Copilot Studio spans normalized to OTEL schema."""
    raw = dlt.read("copilot_studio_traces_raw")
    return raw.select(
        col("conversationid").alias("trace_id"),
        concat_ws("-", lit("cs"), col("conversationid")).alias("span_id"),
        lit("conversation").alias("operation_name"),
        lit("CHAIN").alias("span_type"),
        expr("CAST(NULL AS BIGINT)").alias("start_time_ms"),
        expr("CAST(NULL AS BIGINT)").alias("end_time_ms"),
        col("DurationMs").cast("long").alias("duration_ms"),
        lit("OK").alias("status"),
        lit("copilot_studio").alias("source_system"),
        col("botid").alias("agent_id"),
        col("conversationid").alias("conversation_id"),
        lit(None).cast("string").alias("model"),
        col("content").alias("input_messages"),
        col("content").alias("output_messages"),
        lit(None).cast("string").alias("tool_name"),
        lit(None).cast("string").alias("tool_result"),
        lit(None).cast("int").alias("input_tokens"),
        lit(None).cast("int").alias("output_tokens"),
        lit(None).cast("string").alias("attributes"),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ### ServiceNow Spans (Stub)

# COMMAND ----------

@dlt.table(
    name="servicenow_spans",
    comment="[STUB] Normalized spans from ServiceNow Virtual Agent",
    table_properties={"quality": "silver"},
)
def servicenow_spans():
    """Silver batch table: Stub ServiceNow spans normalized to OTEL schema."""
    raw = dlt.read("servicenow_traces_raw")
    return raw.select(
        col("sys_id").alias("trace_id"),
        concat_ws("-", lit("sn"), col("sys_id")).alias("span_id"),
        col("virtual_agent_topic").alias("operation_name"),
        lit("CHAIN").alias("span_type"),
        expr("CAST(NULL AS BIGINT)").alias("start_time_ms"),
        expr("CAST(NULL AS BIGINT)").alias("end_time_ms"),
        col("DurationMs").cast("long").alias("duration_ms"),
        when(col("resolution_code") == "Resolved", lit("OK")).otherwise(lit("ERROR")).alias("status"),
        lit("servicenow").alias("source_system"),
        lit("virtual-agent").alias("agent_id"),
        col("sys_id").alias("conversation_id"),
        lit(None).cast("string").alias("model"),
        col("messages").alias("input_messages"),
        col("messages").alias("output_messages"),
        lit(None).cast("string").alias("tool_name"),
        lit(None).cast("string").alias("tool_result"),
        lit(None).cast("int").alias("input_tokens"),
        lit(None).cast("int").alias("output_tokens"),
        lit(None).cast("string").alias("attributes"),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold Layer — Agent Conversations

# COMMAND ----------

# MAGIC %md
# MAGIC ### All Spans (Union)

# COMMAND ----------

@dlt.table(
    name="all_spans",
    comment="Union of all normalized agent spans across source systems",
    table_properties={"quality": "gold"},
)
def all_spans():
    """Gold materialized view: Union of all silver span tables."""
    foundry = dlt.read("foundry_spans")
    salesforce = dlt.read("salesforce_spans")
    copilot = dlt.read("copilot_studio_spans")
    servicenow = dlt.read("servicenow_spans")
    return (
        foundry
        .unionByName(salesforce)
        .unionByName(copilot)
        .unionByName(servicenow)
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ### Agent Conversations (Aggregated)

# COMMAND ----------

@dlt.table(
    name="agent_conversations",
    comment="Agent conversations aggregated from spans — ready for MLflow trace upload",
    table_properties={
        "quality": "gold",
        "pipelines.autoOptimize.zOrderCols": "conversation_id",
    },
)
def agent_conversations():
    """Gold materialized view: Conversations with aggregated metrics and span arrays."""
    spans = dlt.read("all_spans")
    return (
        spans.groupBy(
            coalesce(col("conversation_id"), col("trace_id")).alias("conversation_id"),
            col("source_system"),
        )
        .agg(
            first("agent_id", ignorenulls=True).alias("agent_id"),
            spark_min("start_time_ms").alias("conversation_start_ms"),
            spark_max("end_time_ms").alias("conversation_end_ms"),
            (spark_max("end_time_ms") - spark_min("start_time_ms")).alias("total_duration_ms"),
            count("*").alias("span_count"),
            spark_sum("input_tokens").alias("total_input_tokens"),
            spark_sum("output_tokens").alias("total_output_tokens"),
            first("model", ignorenulls=True).alias("model"),
            collect_list(
                struct(
                    "trace_id", "span_id", "operation_name", "span_type",
                    "start_time_ms", "end_time_ms", "duration_ms", "status",
                    "model", "input_messages", "output_messages",
                    "tool_name", "tool_result", "input_tokens", "output_tokens",
                    "attributes",
                )
            ).alias("spans"),
            first(
                when(col("input_messages").contains('"user"'), col("input_messages")),
                ignorenulls=True,
            ).alias("user_message_json"),
        )
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ### MLflow Trace Upload
# MAGIC
# MAGIC Final pipeline stage: reads `agent_conversations`, uploads each as an MLflow trace
# MAGIC with proper span hierarchy, and produces an audit table of uploaded traces.
# MAGIC
# MAGIC ```
# MAGIC agent_conversations → mlflow_trace_uploads (audit)
# MAGIC ```

# COMMAND ----------

import mlflow
from mlflow.tracking import MlflowClient
from mlflow.entities import SpanType

MLFLOW_EXPERIMENT_NAME = "/Shared/Agent traces"


def safe_parse_json(s):
    """Parse JSON string, returning original string on failure."""
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def extract_user_message(spans):
    """Extract the first user message from a list of span rows."""
    for span in spans:
        msgs = safe_parse_json(span.input_messages)
        if isinstance(msgs, list):
            for m in msgs:
                if isinstance(m, dict) and m.get("role") == "user":
                    parts = m.get("parts", [])
                    if parts:
                        return parts[0].get("content", "")
        elif isinstance(msgs, str) and msgs:
            return msgs
    return ""


def extract_assistant_response(spans):
    """Extract the last assistant response from a list of span rows."""
    for span in reversed(spans):
        msgs = safe_parse_json(span.output_messages)
        if isinstance(msgs, list):
            for m in msgs:
                if isinstance(m, dict) and m.get("role") == "assistant":
                    parts = m.get("parts", [])
                    if parts and parts[0].get("content"):
                        return parts[0]["content"]
        elif isinstance(msgs, str) and msgs:
            return msgs
    return ""


def build_span_inputs(span):
    """Build input dict for an MLflow span."""
    inputs = {}
    msgs = safe_parse_json(span.input_messages)
    if isinstance(msgs, list):
        for msg in msgs:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            parts = msg.get("parts", [])
            text = parts[0].get("content", "")[:2000] if parts else ""
            if role == "user":
                inputs["user_message"] = text
            elif role == "developer":
                inputs["system_prompt"] = text[:500]
            elif role == "tool":
                inputs["tool_response"] = text[:1000]
    elif isinstance(msgs, str) and msgs:
        inputs["message"] = msgs[:2000]
    if span.tool_name:
        inputs["tool_name"] = span.tool_name
    return inputs if inputs else {"request": span.operation_name or ""}


def build_span_outputs(span):
    """Build output dict for an MLflow span."""
    outputs = {}
    msgs = safe_parse_json(span.output_messages)
    if isinstance(msgs, list):
        for msg in msgs:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            parts = msg.get("parts", [])
            if parts:
                content = parts[0].get("content", "")
                if role == "assistant":
                    outputs["assistant_response"] = content[:3000]
                elif role == "developer":
                    outputs["system_content"] = content[:2000]
    elif isinstance(msgs, str) and msgs:
        outputs["response"] = msgs[:3000]
    if span.tool_result:
        outputs["tool_result"] = str(span.tool_result)[:2000]
    return outputs if outputs else {"result": span.status or ""}


def build_span_attributes(span):
    """Build attributes dict for an MLflow span."""
    attrs = {}
    if span.model:
        attrs["gen_ai.request.model"] = span.model
    if span.input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = str(span.input_tokens)
    if span.output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = str(span.output_tokens)
    if span.duration_ms is not None:
        attrs["duration_ms"] = str(span.duration_ms)
    if span.tool_name:
        attrs["gen_ai.tool.name"] = span.tool_name
    extra = safe_parse_json(span.attributes)
    if isinstance(extra, dict):
        attrs.update({k: str(v) for k, v in extra.items()})
    return attrs


def upload_conversation_to_mlflow(conv, client, experiment_id):
    """Upload a single conversation as an MLflow trace. Returns (trace_id, status)."""
    spans = sorted(conv.spans, key=lambda s: s.start_time_ms or 0)
    if not spans:
        return (None, "SKIPPED", "no spans")

    start_ms = conv.conversation_start_ms or (spans[0].start_time_ms or 0)
    end_ms = conv.conversation_end_ms or (spans[-1].end_time_ms or start_ms)

    user_msg = extract_user_message(spans)
    assistant_resp = extract_assistant_response(spans)

    root_span = client.start_trace(
        name=f"Conversation: {conv.agent_id or conv.conversation_id}",
        span_type=SpanType.AGENT,
        experiment_id=experiment_id,
        inputs={"user_message": user_msg[:2000]},
        tags={
            "source_system": conv.source_system,
            "agent_id": conv.agent_id or "",
            "conversation_id": conv.conversation_id,
            "span_count": str(conv.span_count),
        },
        start_time_ns=start_ms * 1_000_000,
    )
    trace_id = root_span.trace_id
    root_span_id = root_span.span_id

    last_chat_span_id = None
    for span in spans:
        span_type_str = span.span_type or "CHAIN"
        span_type = getattr(SpanType, span_type_str, SpanType.CHAIN)
        op_name = span.operation_name or "unknown"

        rec_start_ms = span.start_time_ms or start_ms
        rec_end_ms = span.end_time_ms or (rec_start_ms + (span.duration_ms or 0))

        if span_type_str == "CHAT_MODEL" or (op_name and "chat" in op_name):
            parent_id = root_span_id
        elif span_type_str == "TOOL" and last_chat_span_id:
            parent_id = last_chat_span_id
        elif last_chat_span_id:
            parent_id = last_chat_span_id
        else:
            parent_id = root_span_id

        child = client.start_span(
            name=op_name,
            trace_id=trace_id,
            parent_id=parent_id,
            span_type=span_type,
            inputs=build_span_inputs(span),
            start_time_ns=rec_start_ms * 1_000_000,
        )
        client.end_span(
            trace_id=trace_id,
            span_id=child.span_id,
            outputs=build_span_outputs(span),
            attributes=build_span_attributes(span),
            status="OK" if span.status == "OK" else "ERROR",
            end_time_ns=rec_end_ms * 1_000_000,
        )
        if span_type_str == "CHAT_MODEL" or (op_name and "chat" in op_name):
            last_chat_span_id = child.span_id

    client.end_trace(
        trace_id=trace_id,
        outputs={"assistant_response": assistant_resp[:2000]},
        attributes={
            "conversation_id": conv.conversation_id,
            "source_system": conv.source_system,
            "agent_id": conv.agent_id or "",
            "total_input_tokens": str(conv.total_input_tokens or 0),
            "total_output_tokens": str(conv.total_output_tokens or 0),
            "span_count": str(conv.span_count),
        },
        end_time_ns=end_ms * 1_000_000,
    )
    return (trace_id, "OK", f"{conv.span_count} spans")


@dlt.table(
    name="mlflow_trace_uploads",
    comment="Audit log of agent conversations uploaded to MLflow traces",
    table_properties={"quality": "gold"},
)
def mlflow_trace_uploads():
    """Gold table: Upload conversations to MLflow and return audit records.

    Uses spark.table() to read from the materialized UC table instead of
    dlt.read(), because dlt.read().collect() returns empty in DLT context.
    The DLT dependency is implicit via table ordering (agent_conversations
    is defined before this table).
    """
    from datetime import datetime

    conversations = (
        spark.table(f"{catalog}.traces.agent_conversations")
        .filter("source_system = 'foundry'")
        .collect()
    )

    experiment = mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    experiment_id = experiment.experiment_id
    client = MlflowClient()

    audit_rows = []
    for conv in conversations:
        # Check for existing trace
        existing = client.search_traces(
            experiment_ids=[experiment_id],
            filter_string=f"tag.conversation_id = '{conv.conversation_id}' AND tag.source_system = '{conv.source_system}'",
            max_results=1,
        )
        if existing:
            old_span_count = int(existing[0].tags.get("span_count", "0"))
            if old_span_count >= conv.span_count:
                audit_rows.append({
                    "conversation_id": conv.conversation_id,
                    "source_system": conv.source_system,
                    "mlflow_trace_id": existing[0].trace_id,
                    "span_count": conv.span_count,
                    "status": "SKIPPED",
                    "message": "already up-to-date",
                    "uploaded_at": datetime.utcnow().isoformat(),
                })
                continue
            try:
                client.delete_traces(
                    experiment_id=experiment_id,
                    trace_ids=[existing[0].trace_id],
                )
            except Exception:
                pass

        try:
            trace_id, status, message = upload_conversation_to_mlflow(conv, client, experiment_id)
            audit_rows.append({
                "conversation_id": conv.conversation_id,
                "source_system": conv.source_system,
                "mlflow_trace_id": trace_id or "",
                "span_count": conv.span_count,
                "status": status,
                "message": message,
                "uploaded_at": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            audit_rows.append({
                "conversation_id": conv.conversation_id,
                "source_system": conv.source_system,
                "mlflow_trace_id": "",
                "span_count": conv.span_count,
                "status": "ERROR",
                "message": str(e)[:500],
                "uploaded_at": datetime.utcnow().isoformat(),
            })

    if not audit_rows:
        audit_rows = [{
            "conversation_id": "", "source_system": "", "mlflow_trace_id": "",
            "span_count": 0, "status": "EMPTY", "message": "no conversations",
            "uploaded_at": datetime.utcnow().isoformat(),
        }]

    return spark.createDataFrame(audit_rows)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Output Schema Reference
# MAGIC
# MAGIC ### Silver (all sources)
# MAGIC | Column | Type | Description |
# MAGIC |--------|------|-------------|
# MAGIC | trace_id | STRING | Operation/conversation identifier |
# MAGIC | span_id | STRING | Unique span identifier |
# MAGIC | operation_name | STRING | e.g., "chat gpt-4o", "execute_tool search" |
# MAGIC | span_type | STRING | AGENT, CHAT_MODEL, TOOL, CHAIN |
# MAGIC | start/end_time_ms | LONG | Epoch milliseconds |
# MAGIC | source_system | STRING | foundry, salesforce, copilot_studio, servicenow |
# MAGIC | conversation_id | STRING | Conversation/thread ID |
# MAGIC | input/output_messages | STRING | JSON arrays |
# MAGIC | input/output_tokens | INT | Token usage |
# MAGIC
# MAGIC ### Gold (`agent_conversations`)
# MAGIC | Column | Type | Description |
# MAGIC |--------|------|-------------|
# MAGIC | conversation_id | STRING | Primary key |
# MAGIC | source_system | STRING | Source platform |
# MAGIC | spans | ARRAY&lt;STRUCT&gt; | All spans for this conversation |
# MAGIC | total_duration_ms | LONG | End - Start |
# MAGIC | total_input/output_tokens | LONG | Sum of tokens |
# MAGIC
# MAGIC ### Querying
# MAGIC ```sql
# MAGIC -- Bronze: raw Foundry traces
# MAGIC SELECT time, Name, OperationId, DurationMs FROM traces.foundry_traces_raw LIMIT 10;
# MAGIC
# MAGIC -- Silver: normalized spans across sources
# MAGIC SELECT source_system, span_type, operation_name, duration_ms FROM traces.all_spans;
# MAGIC
# MAGIC -- Gold: conversations
# MAGIC SELECT conversation_id, source_system, span_count, total_duration_ms
# MAGIC FROM traces.agent_conversations;
# MAGIC ```
