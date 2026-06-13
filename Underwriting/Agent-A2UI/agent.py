"""Underwriting Workbench Agent — ADK + A2UI for Gemini Enterprise."""

import json
import logging
import os
from typing import Dict, Optional

from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Part, TextPart
from a2ui.a2a import get_a2ui_agent_extension, parse_response_to_parts
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.core.parser.parser import parse_response
from a2ui.core.schema.common_modifiers import remove_strict_validation
from a2ui.core.schema.constants import A2UI_CLOSE_TAG, A2UI_OPEN_TAG, VERSION_0_8
from a2ui.core.schema.manager import A2uiSchemaManager
import dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.genai.errors import ServerError
import jsonschema
from prompt_builder import ROLE_DESCRIPTION, UI_DESCRIPTION, WORKFLOW_DESCRIPTION, get_text_prompt

# Import our underwriting tools
from orchestrator_agent.tools import (
    classify_submission, extract_submission, fetch_rules,
    fetch_client_history, evaluate_uw_rules, save_submission,
    record_decision, get_submission, list_submissions,
    update_submission, justify_submission, get_prioritized_workload,
    update_review_status, log_processing_error, get_processing_errors,
    resolve_processing_error, save_pending_classification,
)

logger = logging.getLogger(__name__)
dotenv.load_dotenv()

SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

# All 17 tools
ALL_TOOLS = [
    classify_submission, extract_submission, fetch_rules,
    fetch_client_history, evaluate_uw_rules, save_submission,
    record_decision, get_submission, list_submissions,
    update_submission, justify_submission, get_prioritized_workload,
    update_review_status, log_processing_error, get_processing_errors,
    resolve_processing_error, save_pending_classification,
]


class UnderwritingAgent:
    """Smart Underwriting Workbench agent with A2UI support."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._agent_name = "underwriting_workbench"
        self._user_id = "remote_agent"
        self._text_runner = self._build_runner(self._build_llm_agent())

        self._schema_managers: Dict[str, A2uiSchemaManager] = {}
        self._ui_runners: Dict[str, Runner] = {}

        for version in [VERSION_0_8]:
            schema_manager = self._build_schema_manager(version)
            self._schema_managers[version] = schema_manager
            agent = self._build_llm_agent(schema_manager)
            self._ui_runners[version] = self._build_runner(agent)

        self._agent_card = self._build_agent_card()

    @property
    def agent_card(self) -> AgentCard:
        return self._agent_card

    def _build_schema_manager(self, version: str) -> A2uiSchemaManager:
        return A2uiSchemaManager(
            version=version,
            catalogs=[
                BasicCatalog.get_config(
                    version=version,
                    examples_path=os.path.join(os.path.dirname(__file__), f"examples/{version}"),
                )
            ],
            schema_modifiers=[remove_strict_validation],
        )

    def _build_agent_card(self) -> AgentCard:
        extensions = []
        for version, sm in self._schema_managers.items():
            ext = get_a2ui_agent_extension(version, sm.accepts_inline_catalogs, sm.supported_catalog_ids)
            extensions.append(ext)

        return AgentCard(
            name="Smart Underwriting Workbench",
            description="AI-powered insurance submission processing and underwriter assistant. Process ACORD submissions, review risk scores, accept/decline decisions.",
            url=self.base_url,
            version="1.0.0",
            default_input_modes=SUPPORTED_CONTENT_TYPES,
            default_output_modes=SUPPORTED_CONTENT_TYPES,
            capabilities=AgentCapabilities(streaming=True, extensions=extensions),
            preferred_transport="JSONRPC",
            skills=[
                AgentSkill(id="process_submission", name="Process Submission", description="Process insurance submissions from GCS", tags=["insurance", "underwriting", "acord"]),
                AgentSkill(id="review_submissions", name="Review Submissions", description="Dashboard, prioritization, details, justification", tags=["dashboard", "review", "priority"]),
                AgentSkill(id="decide", name="Accept/Decline", description="Record underwriter decisions", tags=["accept", "decline", "decision"]),
            ],
        )

    def _build_runner(self, agent: LlmAgent) -> Runner:
        return Runner(
            app_name=self._agent_name,
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    def _build_llm_agent(self, schema_manager: Optional[A2uiSchemaManager] = None) -> LlmAgent:
        instruction = (
            schema_manager.generate_system_prompt(
                role_description=ROLE_DESCRIPTION,
                workflow_description=WORKFLOW_DESCRIPTION,
                ui_description=UI_DESCRIPTION,
                include_schema=True,
                include_examples=True,
                validate_examples=True,
            )
            if schema_manager
            else get_text_prompt()
        )

        return LlmAgent(
            model=os.getenv("MODEL", "gemini-2.5-pro"),
            name=self._agent_name,
            description="Smart Underwriting Workbench — processes insurance submissions and assists underwriters.",
            instruction=instruction,
            tools=ALL_TOOLS,
        )

    async def fetch_response(self, query: str, session_id: str, ui_version: Optional[str] = None) -> list[Part]:
        session_state = {"base_url": self.base_url}

        if ui_version:
            runner = self._ui_runners[ui_version]
            schema_manager = self._schema_managers[ui_version]
            selected_catalog = schema_manager.get_selected_catalog()
        else:
            runner = self._text_runner
            selected_catalog = None

        session = await runner.session_service.get_session(
            app_name=self._agent_name, user_id=self._user_id, session_id=session_id,
        )
        if session is None:
            session = await runner.session_service.create_session(
                app_name=self._agent_name, user_id=self._user_id, state=session_state, session_id=session_id,
            )

        # Validation + retry logic
        max_retries = 1
        attempt = 0
        current_query_text = query

        if ui_version and (not selected_catalog or not selected_catalog.catalog_schema):
            return [Part(root=TextPart(text="Internal UI configuration error. Please contact support."))]

        while attempt <= max_retries:
            attempt += 1
            current_message = types.Content(role="user", parts=[types.Part.from_text(text=current_query_text)])
            full_content_list = []

            try:
                async for event in runner.run_async(
                    user_id=self._user_id, session_id=session.id, new_message=current_message,
                ):
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            full_content_list.extend([p.text for p in event.content.parts if p.text])
            except ServerError as e:
                logger.error(f"GenAI ServerError: {e}")
                return [Part(root=TextPart(text=f"Error: {e}"))]

            final_response_content = "".join(full_content_list)

            if not final_response_content:
                if attempt <= max_retries:
                    current_query_text = f"No response received. Please retry: '{query}'"
                    continue
                else:
                    return [Part(root=TextPart(text="Sorry, I couldn't process your request. Please try again."))]

            is_valid = False
            error_message = ""

            if ui_version:
                try:
                    response_parts = parse_response(final_response_content)
                    for part in response_parts:
                        if not part.a2ui_json:
                            continue
                        parsed = part.a2ui_json
                        if parsed == []:
                            is_valid = True
                        else:
                            selected_catalog.validator.validate(parsed)
                            is_valid = True
                except (ValueError, json.JSONDecodeError, jsonschema.exceptions.ValidationError) as e:
                    logger.warning(f"A2UI validation failed (attempt {attempt}): {e}")
                    error_message = f"Validation failed: {e}."
            else:
                is_valid = True

            if is_valid:
                if ui_version:
                    return parse_response_to_parts(final_response_content)
                else:
                    return [Part(root=TextPart(text=final_response_content))]

            if attempt <= max_retries:
                current_query_text = (
                    f"Your previous response was invalid. {error_message} "
                    f"Generate a valid A2UI JSON response wrapped in '{A2UI_OPEN_TAG}' and '{A2UI_CLOSE_TAG}' tags. "
                    f"Retry: '{query}'"
                )

        return [Part(root=TextPart(text="Sorry, I'm having trouble generating the interface. Please try again."))]
