# A2A Gateway Test Suite

## Running Tests

```bash
# Install test dependencies
pip install -r tests/requirements.txt

# Run all tests (unit + integration + A2A compliance)
make test PREFIX=$PREFIX

# Run only unit tests (no external services needed)
make test-unit

# Run only integration tests
python -m tests.run_tests --integration --prefix $PREFIX
```

## Test Suite (85 tests)

| Category | Tests | Description |
|----------|-------|-------------|
| Unit: Models | 9 | AgentInfo, OAuthM2M, responses |
| Unit: Authorization | 10 | User email extraction, grants checking |
| Unit: Agents | 8 | Echo returns input, Calculator (2+2=4, etc.) |
| Unit: Orchestrator | 17 | Text extraction, conversation history, streaming |
| Integration: Gateway | 13 | Health, discovery, auth (valid/invalid tokens) |
| Integration: A2A Compliance | 25 | Agent card, JSON-RPC, task states, streaming |
| Integration: Access Control | 3 | Grant/revoke USE_CONNECTION workflow |

## Unit Tests

Unit tests can run without any external services or deployed infrastructure.

### Models (`test_models.py`)
- `AgentInfo` validation and serialization
- `OAuthM2MCredentials` required fields
- `AgentListResponse` and `HealthResponse` structures

### Authorization (`test_authorization.py`)
- User email extraction from headers (`X-Forwarded-Email`, `X-User-Email`)
- Connection access checking (owner vs granted access)
- `USE_CONNECTION` privilege verification

### Agents (`test_agents.py`)
- Echo agent returns input correctly
- Calculator agent arithmetic operations (add, subtract, multiply, divide)
- Agent card structure validation

*Note: Agent tests require `ECHO_AGENT_URL` and `CALCULATOR_AGENT_URL` environment variables.*

### Orchestrator (`test_orchestrator.py`)
- Text extraction from various content formats (string, list, dict, objects)
- `ResponseInputTextParam` format handling for multi-turn conversations
- Conversation history extraction
- Streaming message separation

## Integration Tests

Integration tests require deployed infrastructure (gateway and agents).

### Gateway (`test_gateway.py`)
- Health endpoint responses
- Agent discovery endpoints
- Authentication with valid/invalid tokens
- Error handling

### A2A Compliance (`test_a2a_compliance.py`)
- Agent card structure per A2A spec
- JSON-RPC message format
- Task state transitions
- SSE streaming responses

### Access Control (`test_access_control.py`)
- Grant `USE_CONNECTION` workflow
- Revoke access workflow
- 403 responses for unauthorized access

## Environment Variables

| Variable | Required For | Description |
|----------|--------------|-------------|
| `PREFIX` | Integration tests | Your deployment prefix |
| `ECHO_AGENT_URL` | Agent unit tests | Echo agent base URL |
| `CALCULATOR_AGENT_URL` | Agent unit tests | Calculator agent base URL |
| `GATEWAY_URL` | Integration tests | Gateway base URL (auto-discovered if PREFIX set) |
