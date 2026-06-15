"""AgentExecutor for the A2A underwriting chat agent."""
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, TextPart, UnsupportedOperationError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError
from google.adk import Runner
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.sessions import InMemorySessionService
from google.genai import types

from tools import (
    query_submissions,
    get_submission_detail,
    get_urgency_ranking,
    get_portfolio_stats,
    explain_risk_score,
    get_rules_summary,
    get_pending_approvals,
    get_processing_errors,
)

SYSTEM_INSTRUCTION = """You are a senior underwriting analyst assistant for the Smart Underwriting Workbench. You support professional underwriters with data-driven insights, clear explanations, and actionable recommendations.

CRITICAL: You must ALWAYS call a tool to retrieve data before answering. Do not rely on memory or assumptions. Every claim must be backed by tool output.

Response format: Use markdown. Use **bold** for key numbers and case IDs. Use bullet points for lists. Keep responses concise but thorough.
"""


def _build_agent() -> LlmAgent:
    """Build the LlmAgent with tools."""
    return LlmAgent(
        model="gemini-2.0-flash",
        name="smart_underwriter_agent",
        description="Professional underwriting chat assistant.",
        instruction=SYSTEM_INSTRUCTION,
        tools=[
            FunctionTool(query_submissions),
            FunctionTool(get_submission_detail),
            FunctionTool(get_urgency_ranking),
            FunctionTool(get_portfolio_stats),
            FunctionTool(explain_risk_score),
            FunctionTool(get_rules_summary),
            FunctionTool(get_pending_approvals),
            FunctionTool(get_processing_errors),
        ],
    )


def create_executor() -> "UnderwritingAgentExecutor":
    """Factory function for the executor — called by A2aAgent at runtime."""
    return UnderwritingAgentExecutor()


class UnderwritingAgentExecutor(AgentExecutor):
    """Routes A2A messages to the underwriting LlmAgent via ADK Runner."""

    def __init__(self):
        self.runner = None

    def _init_runner(self):
        if not self.runner:
            agent = _build_agent()
            self.runner = Runner(
                app_name=agent.name,
                agent=agent,
                artifact_service=InMemoryArtifactService(),
                session_service=InMemorySessionService(),
                memory_service=InMemoryMemoryService(),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise ServerError(error=UnsupportedOperationError())

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self._init_runner()

        if not context.message:
            return

        user_id = (
            context.message.metadata.get("user_id")
            if context.message and context.message.metadata
            else "servicenow_user"
        )

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task:
            await updater.submit()
        await updater.start_work()

        query = context.get_user_input()
        content = types.Content(role="user", parts=[types.Part(text=query)])

        try:
            session = await self.runner.session_service.get_session(
                app_name=self.runner.app_name,
                user_id=user_id,
                session_id=context.context_id,
            ) or await self.runner.session_service.create_session(
                app_name=self.runner.app_name,
                user_id=user_id,
                session_id=context.context_id,
            )

            final_event = None
            async for event in self.runner.run_async(
                session_id=session.id,
                user_id=user_id,
                new_message=content,
            ):
                if event.is_final_response():
                    final_event = event

            if final_event and final_event.content and final_event.content.parts:
                response_text = "".join(
                    part.text
                    for part in final_event.content.parts
                    if hasattr(part, "text") and part.text
                )
                if response_text:
                    await updater.add_artifact(
                        [TextPart(text=response_text)],
                        name="result",
                    )
                    await updater.complete()
                    return

            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message("Failed to generate response."),
                final=True,
            )

        except Exception as e:
            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(f"Error: {str(e)}"),
                final=True,
            )
