"""General chat tool."""

from __future__ import annotations

from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage
from langchain.tools import BaseTool, tool
from pydantic import BaseModel, Field

class GeneralChatArgs(BaseModel):
    """Arguments for a general chat query.

    This class defines the schema for the arguments required to perform a general chat query.
    It includes a single field for the user's query or message.

    Attributes:
        query: The user's question or message for a general chat response.
    """

    query: str = Field(
        ...,
        description="The user's question or message for a general chat response.",
    )


def make_general_chat_tool(llm: BaseChatModel) -> BaseTool:
    """Create a ``general-chat`` tool bound to ``llm``.

    The LLM is captured in the closure at construction time so the tool is a
    plain :func:`@tool`-decorated function (no custom ``BaseTool`` subclass
    fields), which is how recent langchain-core expects tools to be registered.

    :param llm: The LLM instance to use for generating responses.
    :return: A LangChain tool for general conversation.
    """
    chat_model = llm

    @tool(
        "general-chat",
        args_schema=GeneralChatArgs,
        description=(
            "Use this tool as a last resort if no other tool is appropriate for the user's query. "
            "It is for general conversation, questions, and answering 'how-to' style inquiries."
        ),
    )
    def general_chat(query: str) -> str:
        """Send the query directly to the LLM for a conversational response.

        :param query: The user's query or message.
        :return: The LLM's response.
        """
        prompt = f"""You are a helpful and knowledgeable AI assistant. A user has asked a question that does not fit
        any of the specialized tools. Provide a direct, helpful, and conversational answer to their query.

User's query: "{query}"

Your response:"""

        try:
            response = chat_model.invoke([HumanMessage(content=prompt)])
            if hasattr(response, "content"):
                return str(response.content)
            return str(response)
        except Exception as e:
            return f"❌ Error during general chat: {e}"

    return general_chat
