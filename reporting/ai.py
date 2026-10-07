"""
The one place the app calls the AI provider (Google Gemini).

Every call is bounded twice: the SDK's own HTTP timeout, and a hard
deadline behind it in case a response trickles in slowly enough to dodge
the socket timeout. Provider and network failures become AIUnavailable,
which the views turn into a friendly 503. Anything else is a bug and is
left to reach Sentry.
"""
import concurrent.futures
import logging
import os

import requests

# A fast, stable (non-preview) model: report comments are short, and slower "thinking" models
# can run past the timeout.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
logger = logging.getLogger(__name__)

BUSY_MESSAGE = "The writing assistant is busy, please try again in a minute."
# Not "busy": waiting a minute won't help, so say what is wrong and who can fix it.
LIMIT_MESSAGE = ("The writing assistant has reached its usage limit for now. Try again later, "
                 "or write this one yourself.")
KEY_MESSAGE = ("The writing assistant isn't working: the AI provider refused the key. Whoever runs "
               "HouseMaster needs to check GEMINI_API_KEY.")
MODEL_MESSAGE = ("The writing assistant isn't working: the AI model it is set to use wasn't found. Whoever runs "
                 "HouseMaster needs to check GEMINI_MODEL.")
UNUSABLE_MESSAGE = "The writing assistant's answer couldn't be used. Please try again, or write this one yourself."

# A small shared pool, so a call that blows its deadline can be abandoned
# without holding up the request that made it.
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini")


class AIUnavailable(Exception):
    """The provider didn't answer in time, or answered with an error. `detail` is what to tell the user."""

    def __init__(self, message, detail=BUSY_MESSAGE):
        super().__init__(message)
        self.detail = detail


def _explain(exc):
    """What to tell the user about a provider error. Logs the code and status only: the provider's
    message can repeat the key, and the prompt holds student data."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    logger.warning("AI provider error %s %s", code, status)
    message = str(getattr(exc, "message", "") or "")
    if code in (401, 403) or (code == 400 and "api key" in message.lower()):
        return KEY_MESSAGE
    if code == 404:
        return MODEL_MESSAGE
    if code == 429:
        return LIMIT_MESSAGE
    return BUSY_MESSAGE


def model_name():
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def timeout_seconds():
    return int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "20"))


def hard_deadline_seconds():
    return timeout_seconds() + 5


def generate_text(prompt, *, missing_key_message):
    """Send `prompt` to the model and return its text. Raises AIUnavailable or RuntimeError."""
    from google import genai
    from google.genai import errors, types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(missing_key_message)

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_seconds() * 1000))
    future = _pool.submit(client.models.generate_content, model=model_name(), contents=prompt)
    try:
        response = future.result(timeout=hard_deadline_seconds())
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        logger.warning("AI provider took too long to answer (over %s seconds)", hard_deadline_seconds())
        raise AIUnavailable("The AI provider took too long to answer.") from exc
    except errors.APIError as exc:
        raise AIUnavailable(f"The AI provider failed: {type(exc).__name__}", _explain(exc)) from exc
    except (requests.exceptions.RequestException, ConnectionError, TimeoutError) as exc:
        logger.warning("AI provider unreachable: %s", type(exc).__name__)
        raise AIUnavailable(f"The AI provider failed: {type(exc).__name__}") from exc
    return response.text or ""
