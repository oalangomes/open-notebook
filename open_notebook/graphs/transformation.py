import asyncio
import os
import time

from ai_prompter import Prompter
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.notebook import Source
from open_notebook.domain.transformation import DefaultPrompts, Transformation
from open_notebook.exceptions import OpenNotebookError, TimeoutExceededError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content

TRANSFORMATION_TIMEOUT_SECONDS = int(
    os.getenv("OPEN_NOTEBOOK_TRANSFORMATION_TIMEOUT_SECONDS", "180")
)


class TransformationState(TypedDict):
    input_text: str
    source: Source
    transformation: Transformation
    output: str


async def run_transformation(state: dict, config: RunnableConfig) -> dict:
    source_obj = state.get("source")
    source: Source = source_obj if isinstance(source_obj, Source) else None  # type: ignore[assignment]
    content = state.get("input_text")
    assert source or content, "No content to transform"
    transformation: Transformation = state["transformation"]
    source_id = str(source.id) if source and source.id else "unknown"
    transformation_id = str(getattr(transformation, "id", "")) or "unknown"
    transformation_title = getattr(transformation, "title", None) or transformation_id

    try:
        if not content:
            content = source.full_text
        transformation_template_text = transformation.prompt
        default_prompts: DefaultPrompts = DefaultPrompts(transformation_instructions=None)
        if default_prompts.transformation_instructions:
            transformation_template_text = f"{default_prompts.transformation_instructions}\n\n{transformation_template_text}"

        transformation_template_text = f"{transformation_template_text}\n\n# INPUT"

        system_prompt = Prompter(template_text=transformation_template_text).render(
            data=state
        )
        content_str = str(content) if content else ""
        payload = [SystemMessage(content=system_prompt), HumanMessage(content=content_str)]
        chain = await provision_langchain_model(
            str(payload),
            config.get("configurable", {}).get("model_id"),
            "transformation",
            max_tokens=8192,
        )
        logger.info(
            "Starting transformation LLM call source={} transformation={} timeout={}s chars={}",
            source_id,
            transformation_title,
            TRANSFORMATION_TIMEOUT_SECONDS,
            len(content_str),
        )
        start_time = time.perf_counter()

        response = await asyncio.wait_for(
            chain.ainvoke(payload),
            timeout=TRANSFORMATION_TIMEOUT_SECONDS,
        )
        duration = time.perf_counter() - start_time
        logger.info(
            "Completed transformation LLM call source={} transformation={} duration={:.2f}s",
            source_id,
            transformation_title,
            duration,
        )

        # Clean thinking content from the response
        response_content = extract_text_content(response.content)
        cleaned_content = clean_thinking_content(response_content)

        if source:
            await source.add_insight(transformation.title, cleaned_content)

        return {
            "output": cleaned_content,
        }
    except asyncio.TimeoutError as e:
        duration = time.perf_counter() - start_time if "start_time" in locals() else 0.0
        logger.error(
            "Transformation timed out source={} transformation={} timeout={}s duration={:.2f}s",
            source_id,
            transformation_title,
            TRANSFORMATION_TIMEOUT_SECONDS,
            duration,
        )
        raise TimeoutExceededError(
            f"Transformation '{transformation_title}' timed out after "
            f"{TRANSFORMATION_TIMEOUT_SECONDS} seconds for source {source_id}."
        ) from e
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


agent_state = StateGraph(TransformationState)
agent_state.add_node("agent", run_transformation)  # type: ignore[type-var]
agent_state.add_edge(START, "agent")
agent_state.add_edge("agent", END)
graph = agent_state.compile()
