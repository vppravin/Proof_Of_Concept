"""A2UI Agent Executor — handles A2A message flow for the Underwriting Workbench."""

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Part, Task, TaskState, TextPart, UnsupportedOperationError
from a2a.utils import new_agent_parts_message, new_task
from a2a.utils.errors import ServerError
from a2ui.a2a import try_activate_a2ui_extension
from agent import UnderwritingAgent

logger = logging.getLogger(__name__)


class UnderwritingAgentExecutor(AgentExecutor):
    """Handles A2A message flow for the Underwriting Workbench."""

    def __init__(self, agent: UnderwritingAgent):
        self._agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = ""
        ui_event_part = None
        action = None

        active_ui_version = try_activate_a2ui_extension(context, self._agent.agent_card)

        if active_ui_version:
            logger.info(f"A2UI extension active (v{active_ui_version})")
        else:
            logger.info("A2UI not active — text mode")

        # Parse incoming message parts
        if context.message and context.message.parts:
            for part in context.message.parts:
                if isinstance(part.root, DataPart):
                    if "userAction" in part.root.data:
                        ui_event_part = part.root.data["userAction"]
                elif isinstance(part.root, TextPart):
                    pass  # handled below

        # Handle A2UI button actions
        if ui_event_part:
            action = ui_event_part.get("name")
            ctx = ui_event_part.get("context", {})

            if action == "accept_submission":
                case_id = ctx.get("case_id", "")
                query = f"Accept submission {case_id}"
            elif action == "decline_submission":
                case_id = ctx.get("case_id", "")
                query = f"Decline submission {case_id}"
            elif action == "view_details":
                case_id = ctx.get("case_id", "")
                query = f"Show me the details of {case_id}"
            elif action == "justify":
                case_id = ctx.get("case_id", "")
                query = f"Justify {case_id}"
            elif action == "approve_classification":
                case_id = ctx.get("case_id", "")
                query = f"Approve classification for {case_id}"
            elif action == "retry_failed":
                gcs_folder = ctx.get("gcs_folder", "")
                query = f'Retry "{gcs_folder}"'
            else:
                query = f"User action: {action} with context: {ctx}"
        else:
            query = context.get_user_input()

        logger.info(f"Query for orchestrator: '{query}'")

        # Create or get task
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Get response from agent
        final_parts = await self._agent.fetch_response(query, task.context_id, active_ui_version)

        final_state = TaskState.input_required
        if action in ["accept_submission", "decline_submission"]:
            final_state = TaskState.completed

        await updater.update_status(
            final_state,
            new_agent_parts_message(final_parts, task.context_id, task.id),
            final=(final_state == TaskState.completed),
        )

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
