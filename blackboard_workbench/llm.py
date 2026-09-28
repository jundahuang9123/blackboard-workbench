"""Process-local provider adapter for the unmodified SAST client contract.

Credentials stay in the SDK client in memory. Upstream code receives a compatible
client, while requests use the provider profile selected by the workbench.
"""
from itertools import islice
from types import SimpleNamespace


DEFAULT_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1/",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": "http://host.docker.internal:11434/v1",
    "local": "http://host.docker.internal:1234/v1",
}
_LOCAL_PROVIDERS = {"ollama", "local"}
_NATIVE_OPENAI = None


def _native_class():
    """Capture the SDK before installing the isolated upstream facade."""
    global _NATIVE_OPENAI
    if _NATIVE_OPENAI is None:
        try:
            import openai
        except ImportError:
            raise ValueError("The provider client is unavailable. Rebuild the workbench image.") from None
        _NATIVE_OPENAI = openai.OpenAI
    return _NATIVE_OPENAI


def _safe_error(provider, exc):
    """Return a useful category without provider bodies, URLs, or secrets."""
    status = getattr(exc, "status_code", None)
    status = status if isinstance(status, int) and not isinstance(status, bool) else None
    name = type(exc).__name__.lower()
    if status in {401, 403}:
        category = "authentication or permission denied"
    elif status == 429:
        category = "rate limit or quota exceeded"
    elif status == 404:
        category = "model or endpoint unavailable"
    elif status in {400, 422}:
        category = "request rejected"
    elif status is not None and status >= 500:
        category = "provider unavailable"
    elif "timeout" in name:
        category = "request timed out"
    elif "connection" in name:
        category = "connection failed"
    else:
        category = "provider request failed"
    suffix = f"; HTTP {status}" if status is not None else ""
    return ValueError(f"{provider}: {category}{suffix}.")


def _native_client(config):
    provider = config.get("provider", "openai")
    if provider not in DEFAULT_ENDPOINTS:
        raise ValueError("Unknown provider.")
    api_key = config.get("api_key") or ""
    if not api_key and provider not in _LOCAL_PROVIDERS:
        raise ValueError(f"Configure the {provider} API key before starting a model request.")
    endpoint = config.get("endpoint") or DEFAULT_ENDPOINTS[provider]
    native = _native_class()
    try:
        client = native(api_key=api_key or "workbench-local", base_url=endpoint,
                        timeout=90, max_retries=0)
    except Exception as exc:
        raise _safe_error(provider, exc) from None
    return provider, client


class _Completions:
    def __init__(self, client, provider, model):
        self._client, self._provider, self._model = client, provider, model

    def create(self, *, messages, model=None, **kwargs):
        # The saved provider profile is authoritative even if a future upstream
        # component has a different model default.
        selected_model = self._model or model
        if not isinstance(selected_model, str) or not selected_model.strip():
            raise ValueError("Choose a model before starting a model request.")
        if self._provider != "openai":
            if "max_completion_tokens" in kwargs:
                limit = kwargs.pop("max_completion_tokens")
                if "max_tokens" in kwargs and kwargs["max_tokens"] != limit:
                    raise ValueError("Supply only one output token limit.")
                kwargs["max_tokens"] = limit
            kwargs.setdefault("max_tokens", 4096)
        try:
            response = self._client.chat.completions.create(
                model=selected_model, messages=messages, **kwargs)
        except Exception as exc:
            raise _safe_error(self._provider, exc) from None
        try:
            choice = response.choices[0]
            content = choice.message.content
            finish_reason = getattr(choice, "finish_reason", None)
        except (AttributeError, IndexError, TypeError):
            content, finish_reason = None, None
        if finish_reason == "length":
            raise ValueError(f"{self._provider}: the model response was truncated at its output limit.")
        if finish_reason == "content_filter":
            raise ValueError(f"{self._provider}: the model response was blocked by a content filter.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{self._provider}: the model returned no response text.")
        # Preserve the SDK response and usage object. JSON remains the original
        # pipeline's responsibility; this adapter does not invent or repair it.
        return response


def make_client(config):
    """Return the minimal chat client used by SAST and workbench review."""
    provider, native = _native_client(config)
    completions = _Completions(native, provider, config.get("model"))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def list_models(config):
    """List at most 500 advertised models without exposing provider errors."""
    provider, native = _native_client(config)
    try:
        response = native.models.list()
        records = getattr(response, "data", response)
        identifiers = {
            record.id.strip() for record in islice(records, 500)
            if isinstance(getattr(record, "id", None), str)
            and record.id.strip() and len(record.id) <= 256
        }
    except Exception as exc:
        raise _safe_error(provider, exc) from None
    return [{"id": value, "label": value} for value in sorted(identifiers)]


def install_upstream_client(config):
    """Install the facade before importing SAST in its isolated worker.

    The constructor's key is an upstream compatibility sentinel, never the
    selected provider credential. Return the previous SDK symbol for restoration
    in tests; production isolation ends when the worker process exits.
    """
    _native_class()
    import openai
    previous = openai.OpenAI
    # Copy so a mutable caller dictionary cannot change an executing job.
    profile = dict(config)

    def factory(*args, **kwargs):
        return make_client(profile)

    openai.OpenAI = factory
    return previous
