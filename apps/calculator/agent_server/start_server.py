"""Start the MLflow AgentServer for the Calculator agent."""

from mlflow.genai.agent_server import AgentServer

# Import agent to register the @invoke and @stream functions
import agent_server.agent  # noqa: F401

# Create the agent server
agent_server = AgentServer("ResponsesAgent")

# Export app for uvicorn
app = agent_server.app


def main():
    """Run the agent server."""
    agent_server.run(app_import_string="agent_server.start_server:app")


if __name__ == "__main__":
    main()
