"""Parsers translate framework-specific code into the shared IR."""

from injectguard.parsers.base import FrameworkParser
from injectguard.parsers.langgraph import LangGraphParser
from injectguard.parsers.openai_agents import OpenAIAgentsParser

__all__ = ["FrameworkParser", "LangGraphParser", "OpenAIAgentsParser"]
