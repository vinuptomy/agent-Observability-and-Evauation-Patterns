"""Exception hierarchy — catch ``AgenticEvalError`` to handle every library error."""


class AgenticEvalError(Exception):
    """Base class for all agentic_eval errors."""


class ConfigurationError(AgenticEvalError):
    """Invalid or incomplete configuration (e.g. a judge metric without a judge)."""


class JudgeError(AgenticEvalError):
    """The LLM judge failed or returned an unparseable response after all retries."""


class DatasetError(AgenticEvalError):
    """The evaluation dataset is invalid or violates security limits."""


class AdapterError(AgenticEvalError):
    """A framework adapter could not translate framework events into a Trace."""


class SecurityError(AgenticEvalError):
    """A security policy was violated (e.g. a non-allow-listed target module)."""
