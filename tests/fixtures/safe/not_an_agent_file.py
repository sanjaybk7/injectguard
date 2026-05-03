"""Safe: a generic file that names a class `Agent` but is unrelated to any LLM SDK."""


class Agent:
    """A book agent. Nothing to do with LLMs."""

    def __init__(self, name: str) -> None:
        self.name = name


def send_email(to: str) -> None:
    """Generic helper, not an LLM tool."""


book_agent = Agent(name="literary")
