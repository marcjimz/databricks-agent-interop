# Databricks notebook source
# MAGIC %md
# MAGIC # Foundry Agent Traces → MLflow Traces
# MAGIC
# MAGIC Reads Azure AI Foundry agent trace exports from Blob Storage and reconstructs
# MAGIC them as **MLflow traces** with proper span trees for visualization in the
# MAGIC Databricks MLflow Traces UI.
# MAGIC
# MAGIC ### How it works
# MAGIC 1. Reads NDJSON files from `insights-logs-appdependencies` container
# MAGIC 2. Groups records by `OperationId` (one trace per agent conversation)
# MAGIC 3. Reconstructs the span tree: agent root → LLM calls, tool executions, messages
# MAGIC 4. Logs each conversation as an MLflow trace with full input/output messages
# MAGIC
# MAGIC ### Data path
# MAGIC ```
# MAGIC insights-logs-appdependencies/
# MAGIC   resourceId=/SUBSCRIPTIONS/{sub}/RESOURCEGROUPS/{rg}/
# MAGIC     PROVIDERS/MICROSOFT.INSIGHTS/COMPONENTS/{appi}/
# MAGIC       y=YYYY/m=MM/d=DD/h=HH/m=MM/PT1H.json
# MAGIC ```

# COMMAND ----------

# MAGIC %md
# MAGIC ## Install Dependencies

# COMMAND ----------

# MAGIC %pip install mlflow --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

import os

def load_notebook_env():
    """Load environment variables from the notebook-local .env file."""
    try:
        notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        notebook_dir = "/".join(notebook_path.rsplit("/", 1)[:-1])
        env_file_path = f"/Workspace{notebook_dir}/.env"
        with open(env_file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
        print(f"Loaded configuration from {env_file_path}")
    except Exception as e:
        print(f"Note: Could not load .env file: {e}")

load_notebook_env()

# COMMAND ----------

# Derive all settings from PREFIX and SUBSCRIPTION_ID
PREFIX = os.environ.get("PREFIX", "mcpagent03")
SUBSCRIPTION_ID = os.environ.get("SUBSCRIPTION_ID", "")
RESOURCE_GROUP = os.environ.get("RESOURCE_GROUP", f"rg-{PREFIX}")

# Storage account follows the Terraform naming: st{prefix}uc (no hyphens)
STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT", f"st{PREFIX.replace('-', '')}uc")
CONTAINER_NAME = "insights-logs-appdependencies"
APPI_NAME = f"appi-{PREFIX}"

# Build the blob prefix that matches the diagnostic export path structure
RESOURCE_ID_PREFIX = (
    f"resourceId=/SUBSCRIPTIONS/{SUBSCRIPTION_ID.upper()}"
    f"/RESOURCEGROUPS/{RESOURCE_GROUP.upper()}"
    f"/PROVIDERS/MICROSOFT.INSIGHTS"
    f"/COMPONENTS/{APPI_NAME.upper()}"
)

# MLflow
MLFLOW_EXPERIMENT_NAME = "/Shared/Foundry traces"

print(f"Storage Account:  {STORAGE_ACCOUNT}")
print(f"Container:        {CONTAINER_NAME}")
print(f"Resource Prefix:  {RESOURCE_ID_PREFIX}")
print(f"MLflow Experiment: {MLFLOW_EXPERIMENT_NAME}")

if not SUBSCRIPTION_ID:
    print("\nWARNING: SUBSCRIPTION_ID not set. Set it in .env or as a notebook widget.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Read Trace Files via Spark
# MAGIC
# MAGIC Uses the UC external location (`insights-logs-appdependencies` container) so
# MAGIC no credentials are needed — the access connector handles auth.
# MAGIC
# MAGIC Files are NDJSON (one JSON object per line). Each record is a flat App Insights
# MAGIC `AppDependencies` entry with GenAI semantic convention fields in `Properties`.

# COMMAND ----------

import json

# Read all PT1H.json files via Spark (uses UC external location for auth)
abfss_base = f"abfss://{CONTAINER_NAME}@{STORAGE_ACCOUNT}.dfs.core.windows.net"
abfss_path = f"{abfss_base}/{RESOURCE_ID_PREFIX}"

print(f"Reading from: {abfss_base}/...")
print(f"Path prefix:  {RESOURCE_ID_PREFIX[:80]}...")

# List available time partitions
try:
    files = dbutils.fs.ls(abfss_path)
    print(f"Found {len(files)} top-level entries")
except Exception as e:
    # If specific prefix fails, try listing container root and finding the right path
    print(f"Prefix not found, scanning container root...")
    root_files = dbutils.fs.ls(abfss_base + "/")
    print(f"Container root entries: {[f.name for f in root_files]}")
    # Use first resourceId path found
    if root_files:
        abfss_path = root_files[0].path.rstrip("/")
        print(f"Using path: {abfss_path}")

# COMMAND ----------

# Read all JSON files recursively using Spark
# Each line in the NDJSON files becomes a row with a 'value' column
raw_df = spark.read.text(f"{abfss_path}/y=*/m=*/d=*/h=*/m=*/PT1H.json")
print(f"Total lines read: {raw_df.count()}")

# Parse each JSON line into a Python dict
all_records = []
for row in raw_df.collect():
    line = row.value.strip()
    if line:
        try:
            all_records.append(json.loads(line))
        except json.JSONDecodeError:
            pass

print(f"Total records parsed: {len(all_records)}")

if all_records:
    sample = all_records[0]
    props = sample.get("Properties", {})
    print(f"\nSample record:")
    print(f"  Time:       {sample.get('time')}")
    print(f"  Name:       {sample.get('Name')}")
    print(f"  SpanType:   {props.get('span_type')}")
    print(f"  Operation:  {props.get('gen_ai.operation.name')}")
    print(f"  Model:      {props.get('gen_ai.request.model', 'N/A')}")
    print(f"  Agent:      {props.get('gen_ai.agent.id')}")
    print(f"  DurationMs: {sample.get('DurationMs')}")
    print(f"  Success:    {sample.get('Success')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Group Records into Conversations
# MAGIC
# MAGIC Each `OperationId` represents one agent conversation. Records within a
# MAGIC conversation are individual spans: LLM calls, tool executions, and message routing.

# COMMAND ----------

from collections import defaultdict

conversations = defaultdict(list)
for record in all_records:
    op_id = record.get("OperationId", "unknown")
    conversations[op_id].append(record)

# Sort spans within each conversation by time
for op_id in conversations:
    conversations[op_id].sort(key=lambda r: r.get("time", ""))

print(f"Conversations: {len(conversations)}")
print()
for op_id, records in conversations.items():
    props = records[0].get("Properties", {})
    conv_id = props.get("gen_ai.conversation.id", "")[:12]
    agent_id = props.get("gen_ai.agent.id", "")
    span_types = [r.get("Properties", {}).get("span_type", "?") for r in records]
    total_ms = sum(r.get("DurationMs", 0) for r in records)
    print(f"  [{op_id[:12]}...] conv={conv_id} agent={agent_id} "
          f"spans={len(records)} total={total_ms:.0f}ms types={span_types}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Set Up MLflow Experiment

# COMMAND ----------

import mlflow
from mlflow.tracking import MlflowClient

experiment = mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
experiment_id = experiment.experiment_id
client = MlflowClient()

print(f"MLflow version:    {mlflow.__version__}")
print(f"MLflow Experiment: {MLFLOW_EXPERIMENT_NAME}")
print(f"Experiment ID:     {experiment_id}")
print(f"Conversations:     {len(conversations)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Create MLflow Traces
# MAGIC
# MAGIC Uses `MlflowClient.start_trace()` / `start_span()` / `end_span()` / `end_trace()`
# MAGIC with `start_time_ns` / `end_time_ns` parameters (MLflow 3.9.0) to create traces
# MAGIC with the **original App Insights timestamps**.
# MAGIC
# MAGIC ```
# MAGIC Agent (root)
# MAGIC ├── chat gpt-5 (initial LLM reasoning)
# MAGIC ├── other_message (system/tool schema delivery)
# MAGIC ├── chat gpt-5 (LLM decides to call tool)
# MAGIC ├── execute_tool epic_patient_search (tool execution)
# MAGIC ├── chat gpt-5 (LLM processes tool result)
# MAGIC └── chat gpt-5 (final response to user)
# MAGIC ```

# COMMAND ----------

from datetime import datetime

def iso_to_ms(iso_str):
    """Convert ISO 8601 timestamp to milliseconds since epoch."""
    if "." in iso_str:
        base, frac = iso_str.split(".")
        frac = frac.rstrip("Z")[:6]
        iso_str = f"{base}.{frac}+00:00"
    else:
        iso_str = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso_str)
    return int(dt.timestamp() * 1000)


def map_span_type(record):
    """Map App Insights span_type to MLflow span type."""
    props = record.get("Properties", {})
    span_type = props.get("span_type", "")
    op_name = props.get("gen_ai.operation.name", "")
    if span_type == "tool" or op_name == "execute_tool":
        return "TOOL"
    if span_type == "agent" and op_name == "chat":
        return "CHAT_MODEL"
    return "CHAIN"


def safe_parse_json(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def extract_user_message(records):
    for r in records:
        msgs = safe_parse_json(r.get("Properties", {}).get("gen_ai.input.messages"))
        if not isinstance(msgs, list):
            continue
        for m in msgs:
            if m.get("role") == "user":
                parts = m.get("parts", [])
                if parts:
                    return parts[0].get("content", "")
    return ""


def extract_assistant_response(records):
    for r in reversed(records):
        msgs = safe_parse_json(r.get("Properties", {}).get("gen_ai.output.messages"))
        if not isinstance(msgs, list):
            continue
        for m in msgs:
            if m.get("role") == "assistant":
                parts = m.get("parts", [])
                if parts and parts[0].get("content"):
                    return parts[0]["content"]
    return ""


def build_span_inputs(record):
    props = record.get("Properties", {})
    inputs = {}
    input_msgs = safe_parse_json(props.get("gen_ai.input.messages"))
    if input_msgs and isinstance(input_msgs, list):
        for msg in input_msgs:
            role = msg.get("role", "unknown")
            parts = msg.get("parts", [])
            text = parts[0].get("content", "")[:2000] if parts else ""
            if role == "user":
                inputs["user_message"] = text
            elif role == "developer":
                inputs["system_prompt"] = text[:500]
            elif role == "tool":
                inputs["tool_response"] = text[:1000]
    if props.get("gen_ai.tool.name"):
        inputs["tool_name"] = props["gen_ai.tool.name"]
    return inputs if inputs else {"request": record.get("Data", "")}


def build_span_outputs(record):
    props = record.get("Properties", {})
    outputs = {}
    output_msgs = safe_parse_json(props.get("gen_ai.output.messages"))
    if output_msgs and isinstance(output_msgs, list):
        for msg in output_msgs:
            role = msg.get("role", "unknown")
            parts = msg.get("parts", [])
            if parts:
                content = parts[0].get("content", "")
                if role == "assistant":
                    outputs["assistant_response"] = content[:3000]
                elif role == "developer":
                    outputs["system_content"] = content[:2000]
    if props.get("gen_ai.tool.call.result"):
        outputs["tool_result"] = props["gen_ai.tool.call.result"][:2000]
    return outputs if outputs else {"result_code": record.get("ResultCode", "")}


def build_span_attributes(record):
    """Build span attributes dict from an App Insights record."""
    props = record.get("Properties", {})
    measurements = record.get("Measurements", {})
    attrs = {}
    for key in ["gen_ai.request.model", "gen_ai.response.model", "gen_ai.agent.id",
                 "gen_ai.conversation.id", "gen_ai.tool.name", "gen_ai.tool.type"]:
        if props.get(key):
            attrs[key] = str(props[key])
    for key in ["gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "gen_ai.usage.cached_tokens"]:
        if props.get(key):
            attrs[key] = str(int(float(props[key])))
    for key, val in measurements.items():
        attrs[key] = str(int(val) if val == int(val) else val)
    attrs["duration_ms"] = str(record.get("DurationMs", 0))
    attrs["performance_bucket"] = record.get("PerformanceBucket", "")
    attrs["appi.span_id"] = record.get("Id", "")
    attrs["appi.time"] = record.get("time", "")
    return attrs

# COMMAND ----------

from mlflow.entities import SpanStatusCode, SpanType

trace_count = 0

for op_id, records in conversations.items():
    props_first = records[0].get("Properties", {})
    agent_id = props_first.get("gen_ai.agent.id", "unknown")
    conv_id = props_first.get("gen_ai.conversation.id", op_id)

    # Original trace timing from App Insights
    start_ms = iso_to_ms(records[0]["time"])
    end_ms = max(iso_to_ms(r["time"]) + int(r.get("DurationMs", 0)) for r in records)
    total_duration_ms = end_ms - start_ms

    user_msg = extract_user_message(records)
    assistant_resp = extract_assistant_response(records)
    total_input_tokens = sum(r.get("Measurements", {}).get("gen_ai.usage.input_tokens", 0) for r in records)
    total_output_tokens = sum(r.get("Measurements", {}).get("gen_ai.usage.output_tokens", 0) for r in records)

    # 1. Start root trace with original timestamp (nanoseconds)
    root_span = client.start_trace(
        name=f"Conversation: {agent_id}",
        span_type=SpanType.AGENT,
        experiment_id=experiment_id,
        inputs={"user_message": user_msg[:2000]},
        tags={
            "source": "application_insights_export",
            "agent_id": agent_id,
            "conversation_id": conv_id,
            "operation_id": op_id,
        },
        start_time_ns=start_ms * 1_000_000,
    )
    trace_id = root_span.trace_id
    root_span_id = root_span.span_id

    # 2. Create child spans with proper nesting:
    #    - chat/LLM spans are children of root
    #    - execute_tool spans are children of the preceding chat span
    #    - everything else is a child of root
    last_response_span_id = None

    for record in records:
        props = record.get("Properties", {})
        op_name = props.get("gen_ai.operation.name", "")
        span_type_str = map_span_type(record)
        span_type = getattr(SpanType, span_type_str, SpanType.CHAIN)

        rec_start_ms = iso_to_ms(record["time"])
        rec_end_ms = rec_start_ms + int(record.get("DurationMs", 0))
        success = record.get("Success", True)

        # Foundry hierarchy:
        #   Conversation (root)
        #     └── Response (chat spans) → children of root
        #           └── Tools / knowledge / anything else → children of last Response
        if op_name == "chat":
            parent_id = root_span_id
        elif last_response_span_id:
            parent_id = last_response_span_id
        else:
            parent_id = root_span_id

        child = client.start_span(
            name=record.get("Name", "unknown"),
            trace_id=trace_id,
            parent_id=parent_id,
            span_type=span_type,
            inputs=build_span_inputs(record),
            start_time_ns=rec_start_ms * 1_000_000,
        )

        client.end_span(
            trace_id=trace_id,
            span_id=child.span_id,
            outputs=build_span_outputs(record),
            attributes=build_span_attributes(record),
            status="OK" if success else "ERROR",
            end_time_ns=rec_end_ms * 1_000_000,
        )

        # Track last Response so tools nest under it
        if op_name == "chat":
            last_response_span_id = child.span_id

    # 3. End root trace with original end timestamp
    client.end_trace(
        trace_id=trace_id,
        outputs={"assistant_response": assistant_resp[:2000]},
        attributes={
            "agent_id": agent_id,
            "conversation_id": conv_id,
            "total_input_tokens": str(int(total_input_tokens)),
            "total_output_tokens": str(int(total_output_tokens)),
            "span_count": str(len(records)),
        },
        end_time_ns=end_ms * 1_000_000,
    )

    trace_count += 1
    print(f"  Trace {trace_count}: {agent_id} | {len(records)} spans | "
          f"{total_duration_ms}ms | {user_msg[:60]}")

workspace_url = spark.conf.get("spark.databricks.workspaceUrl", "")
traces_url = f"https://{workspace_url}/ml/experiments/{experiment_id}/traces"

print(f"\nCreated {trace_count} traces in experiment: {MLFLOW_EXPERIMENT_NAME}")
print(f"\nView traces: {traces_url}")
displayHTML(f'<a href="{traces_url}" target="_blank">Open Foundry traces in MLflow →</a>')

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC This notebook:
# MAGIC 1. **Connected** to Azure Blob Storage (`insights-logs-appdependencies` container)
# MAGIC 2. **Read** App Insights NDJSON exports containing Foundry agent dependency records
# MAGIC 3. **Grouped** records by `OperationId` into conversations
# MAGIC 4. **Created MLflow traces** via `MlflowClient` with original App Insights timestamps
# MAGIC    (`start_time_ns`/`end_time_ns`), showing:
# MAGIC    - LLM chat completions (`CHAT_MODEL`) with input/output messages and token usage
# MAGIC    - Tool executions (`TOOL`) with tool name and results
# MAGIC    - Message routing (`CHAIN`) with system prompts and tool schemas
# MAGIC
# MAGIC ### View Results
# MAGIC - Open **Experiments → Foundry traces → Traces** tab in the MLflow UI
# MAGIC - Click any trace to see the full span tree with timing waterfall
# MAGIC - Expand spans to see input messages, assistant responses, and tool results
# MAGIC
# MAGIC ### Trace Structure
# MAGIC ```
# MAGIC Conversation: test2:5                            (root AGENT)
# MAGIC ├── chat gpt-5                       23ms        (CHAT_MODEL - Response)
# MAGIC ├── other_message                   685ms        (CHAIN)
# MAGIC ├── chat gpt-5                     2373ms        (CHAT_MODEL - Response)
# MAGIC │   └── execute_tool epic_patient_search 2209ms  (TOOL)
# MAGIC ├── chat gpt-5                     2515ms        (CHAT_MODEL - Response)
# MAGIC └── chat gpt-5                      546ms        (CHAT_MODEL - Response)
# MAGIC ```
