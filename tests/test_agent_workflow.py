import json
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field

import ai_agent
from ai_agent import PreparedAgentRun


class ScriptedChatModel(BaseChatModel):
    responses: list[BaseMessage]
    response_index: int = 0
    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tool_names: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-test-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        response = self._next_response(messages)
        return ChatResult(generations=[ChatGeneration(message=response)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del stop, run_manager, kwargs
        response = self._next_response(messages)
        if not isinstance(response, AIMessage):
            raise AssertionError("Streaming test responses must be assistant messages.")
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=response.content,
                tool_calls=response.tool_calls,
                chunk_position="last",
            )
        )

    def _next_response(self, messages: list[BaseMessage]) -> BaseMessage:
        self.seen_messages.append(messages)
        if self.response_index >= len(self.responses):
            raise AssertionError("The workflow invoked the model too many times.")
        response = self.responses[self.response_index]
        self.response_index += 1
        return response

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del tool_choice, kwargs
        self.bound_tool_names = [
            tool.name if isinstance(tool, BaseTool) else str(tool) for tool in tools
        ]
        return self


def tool_call(query: str, call_id: str, name: str = "tavily_search") -> dict:
    return {
        "name": name,
        "args": {"query": query},
        "id": call_id,
        "type": "tool_call",
    }


def search_tool(calls: list[str], *, fail: bool = False) -> StructuredTool:
    def search(query: str) -> str:
        calls.append(query)
        if fail:
            raise RuntimeError("private provider diagnostic")
        return json.dumps(
            {
                "results": [
                    {
                        "title": f"Result for {query}",
                        "url": f"https://example.com/{len(calls)}",
                        "content": "Verified evidence",
                    }
                ]
            }
        )

    return StructuredTool.from_function(
        func=search,
        name="tavily_search",
        description="Search current public information.",
        args_schema=ai_agent.SearchInput,
    )


def test_no_tool_workflow_has_explicit_model_path_and_preserves_system_boundary():
    model = ScriptedChatModel(responses=[AIMessage(content="Final answer")])
    graph = ai_agent._build_agent_graph(model, [], "Trusted system policy")

    topology = graph.get_graph()
    result = graph.invoke({"messages": [HumanMessage(content="Question")]})

    assert set(topology.nodes) == {
        "__start__",
        "model",
        "validate_tool_calls",
        "__end__",
    }
    assert model.bound_tool_names == []
    assert isinstance(model.seen_messages[0][0], SystemMessage)
    assert model.seen_messages[0][0].content == "Trusted system policy"
    assert not any(isinstance(message, SystemMessage) for message in result["messages"])
    assert result["messages"][-1].content == "Final answer"


def test_explicit_graph_executes_search_and_loops_back_to_model():
    calls: list[str] = []
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call("python release", "s1")]),
            AIMessage(content="Grounded final answer"),
        ]
    )
    graph = ai_agent._build_agent_graph(
        model,
        [search_tool(calls)],
        "Use tools when needed",
    )

    topology = graph.get_graph()
    result = graph.invoke({"messages": [HumanMessage(content="Latest Python?")]})
    outcome = ai_agent._outcome_from_messages(result["messages"], allow_search=True)

    assert {"model", "validate_tool_calls", "tools"}.issubset(topology.nodes)
    assert model.bound_tool_names == ["tavily_search"]
    assert model.response_index == 2
    assert calls == ["python release"]
    assert outcome.reply == "Grounded final answer"
    assert outcome.search.executions[0].query == "python release"
    assert outcome.search.executions[0].status == "succeeded"


def test_three_calls_are_allowed_across_multiple_model_cycles():
    calls: list[str] = []
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[tool_call("one", "s1"), tool_call("two", "s2")],
            ),
            AIMessage(content="", tool_calls=[tool_call("three", "s3")]),
            AIMessage(content="Done"),
        ]
    )
    graph = ai_agent._build_agent_graph(model, [search_tool(calls)], "Policy")

    result = graph.invoke({"messages": [HumanMessage(content="Research")]})

    assert calls == ["one", "two", "three"]
    assert result["messages"][-1].content == "Done"


def test_fourth_call_is_rejected_before_its_external_execution():
    calls: list[str] = []
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    tool_call("one", "s1"),
                    tool_call("two", "s2"),
                    tool_call("three", "s3"),
                ],
            ),
            AIMessage(content="", tool_calls=[tool_call("four", "s4")]),
        ]
    )
    graph = ai_agent._build_agent_graph(model, [search_tool(calls)], "Policy")

    with pytest.raises(ai_agent.AgentToolLimitExceededError, match="three"):
        graph.invoke({"messages": [HumanMessage(content="Research")]})

    assert sorted(calls) == ["one", "three", "two"]
    assert "four" not in calls


def test_oversized_parallel_batch_is_rejected_atomically():
    calls: list[str] = []
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[tool_call(str(index), f"s{index}") for index in range(4)],
            )
        ]
    )
    graph = ai_agent._build_agent_graph(model, [search_tool(calls)], "Policy")

    with pytest.raises(ai_agent.AgentToolLimitExceededError, match="three"):
        graph.invoke({"messages": [HumanMessage(content="Research")]})

    assert calls == []


@pytest.mark.parametrize(
    ("calls", "message"),
    [
        ([tool_call("query", "s1", name="unknown")], "unsupported"),
        ([tool_call("   ", "s1")], "arguments"),
        ([tool_call("query", "s1"), tool_call("other", "s1")], "identifiers"),
    ],
)
def test_invalid_tool_calls_fail_before_execution(calls, message):
    executions: list[str] = []
    model = ScriptedChatModel(responses=[AIMessage(content="", tool_calls=calls)])
    graph = ai_agent._build_agent_graph(
        model,
        [search_tool(executions)],
        "Policy",
    )

    with pytest.raises(ai_agent.InvalidAgentResponseError, match=message):
        graph.invoke({"messages": [HumanMessage(content="Question")]})

    assert executions == []


def test_tool_call_is_rejected_when_search_is_disabled():
    model = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[tool_call("query", "s1")])]
    )
    graph = ai_agent._build_agent_graph(model, [], "Policy")

    with pytest.raises(ai_agent.InvalidAgentResponseError, match="not enabled"):
        graph.invoke({"messages": [HumanMessage(content="Question")]})


def test_safe_tool_failure_is_preserved_as_failed_search_evidence():
    calls: list[str] = []
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call("news", "s1")]),
            AIMessage(content="I could not verify that."),
        ]
    )
    graph = ai_agent._build_agent_graph(
        model,
        [search_tool(calls, fail=True)],
        "Policy",
    )

    result = graph.invoke({"messages": [HumanMessage(content="Question")]})
    outcome = ai_agent._outcome_from_messages(result["messages"], allow_search=True)

    assert calls == ["news"]
    assert outcome.search.executions[0].status == "failed"
    assert "private provider diagnostic" not in json.dumps(result, default=str)


def test_real_graph_stream_preserves_public_progress_and_final_answer():
    calls: list[str] = []
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call("news", "s1")]),
            AIMessage(content="Final answer"),
        ]
    )
    graph = ai_agent._build_agent_graph(model, [search_tool(calls)], "Policy")

    events = list(
        ai_agent.stream_prepared_agent(
            PreparedAgentRun(
                graph,
                {"messages": [HumanMessage(content="Question")]},
                True,
            )
        )
    )

    assert [event.value for event in events if event.type == "status"] == [
        "model_running",
        "search_running",
        "search_results_received",
        "model_running",
        "finalizing",
    ]
    assert (
        "".join(str(event.value) for event in events if event.type == "delta")
        == "Final answer"
    )
    assert events[-1].type == "complete"
    assert events[-1].value.reply == "Final answer"


def test_non_assistant_model_result_fails_at_the_graph_boundary():
    model = ScriptedChatModel(responses=[HumanMessage(content="Wrong role")])
    graph = ai_agent._build_agent_graph(model, [], "Policy")

    with pytest.raises(ai_agent.InvalidAgentResponseError, match="assistant message"):
        graph.invoke({"messages": [HumanMessage(content="Question")]})
