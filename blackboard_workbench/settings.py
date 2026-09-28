"""Server-owned model profiles. Secrets never enter public config or job files."""
from copy import deepcopy
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlsplit
from .store import required_text


PROVIDERS = [
    {"id": "openai", "label": "OpenAI", "kind": "cloud", "requires_key": True,
     "default_endpoint": "https://api.openai.com/v1", "models": [{"id": x, "label": x} for x in ("gpt-5", "gpt-5-mini", "gpt-5-nano")],
     "help": "Uses the OpenAI API. GPT-5 matches the original workflow's default; you can enter another supported model ID."},
    {"id": "anthropic", "label": "Anthropic · Claude", "kind": "cloud", "requires_key": True,
     "default_endpoint": "https://api.anthropic.com/v1", "models": [{"id": x, "label": x} for x in ("claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-5-5")],
     "help": "Uses Claude's OpenAI-compatible API for text chat. Model access depends on your account."},
    {"id": "gemini", "label": "Google · Gemini", "kind": "cloud", "requires_key": True,
     "default_endpoint": "https://generativelanguage.googleapis.com/v1beta/openai", "models": [{"id": x, "label": x} for x in ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview")],
     "help": "Uses Gemini's OpenAI-compatible API. The Pro preset is a preview; test your account and model before a full run."},
    {"id": "mistral", "label": "Mistral", "kind": "cloud", "requires_key": True,
     "default_endpoint": "https://api.mistral.ai/v1", "models": [{"id": x, "label": x} for x in ("mistral-small-2603", "mistral-medium-3-5", "mistral-large-2512")],
     "help": "Uses Mistral's chat API. Presets are model IDs; another available ID can be entered."},
    {"id": "ollama", "label": "Local · Ollama", "kind": "local", "requires_key": False,
     "default_endpoint": "http://host.docker.internal:11434/v1", "models": [{"id": x, "label": x + " (install first)"} for x in ("llama3.1:8b", "qwen3.5:9b", "gemma3:12b")],
     "help": "Start Ollama and download the model on the host first. No key is normally required. The original prompts need a large context window."},
    {"id": "local", "label": "Local · LM Studio / compatible server", "kind": "local", "requires_key": False,
     "default_endpoint": "http://host.docker.internal:1234/v1", "models": [],
     "help": "Start an OpenAI-compatible server and load a model first. Load available models to get its exact ID; supply a token only if that server requires one."},
]
CATALOG = {p["id"]: p for p in PROVIDERS}
ENV_KEYS = {"openai": ("OPENAIKEY", "OPENAI_API_KEY"), "anthropic": ("ANTHROPIC_API_KEY",), "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "mistral": ("MISTRAL_API_KEY",)}


def validate_endpoint(provider, value):
    definition = CATALOG[provider]
    endpoint = (value or definition["default_endpoint"]).strip().rstrip("/")
    if len(endpoint) > 500:
        raise ValueError("The model server address is too long.")
    if definition["kind"] == "cloud":
        if endpoint != definition["default_endpoint"].rstrip("/"):
            raise ValueError("Cloud providers use their fixed official API address.")
        return endpoint
    parsed = urlsplit(endpoint)
    try:
        parsed.port
    except ValueError:
        raise ValueError("Enter a valid local model server port.") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Enter an HTTP(S) local server address without credentials, query parameters, or fragments.")
    host = parsed.hostname.lower()
    local = host in {"localhost", "host.docker.internal"} or host.endswith(".local") or bool(re.fullmatch(r"[a-z0-9-]+", host))
    try:
        address = ipaddress.ip_address(host)
        local = (address.is_loopback or address.is_private) and not (address.is_link_local or address.is_multicast or address.is_unspecified)
    except ValueError:
        pass
    if not local:
        raise ValueError("Local models must use a localhost, Docker host, LAN hostname, or private IP address.")
    if parsed.path.rstrip("/") != "/v1":
        raise ValueError("Use your local server's OpenAI-compatible /v1 address.")
    return endpoint


class ModelSettings:
    def __init__(self, directory, environ=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.environ = dict(os.environ if environ is None else environ)
        self.lock = threading.RLock()
        raw = self._read("model-settings.json")
        self.provider = raw.get("provider", "openai") if raw.get("provider", "openai") in CATALOG else "openai"
        self.profiles = {}
        for provider, definition in CATALOG.items():
            default_model = definition["models"][0]["id"] if definition["models"] else ""
            stored = raw.get("profiles", {}).get(provider, {})
            self.profiles[provider] = {"model": stored.get("model", default_model), "endpoint": validate_endpoint(provider, stored.get("endpoint", definition["default_endpoint"]))}
        self.saved_keys = {k: v for k, v in self._read("credentials.json").items() if k in CATALOG and isinstance(v, str) and v}
        self.session_keys = {}

    def _read(self, name):
        path = self.directory / name
        if not path.exists():
            return {}
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("The local model settings file is invalid.")
        return value

    def _write(self, name, value):
        fd, temporary = tempfile.mkstemp(prefix=".model-", dir=self.directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as file:
                json.dump(value, file)
            os.replace(temporary, self.directory / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _credential(self, provider):
        for source, keys in (("session", self.session_keys), ("saved", self.saved_keys)):
            if keys.get(provider):
                return keys[provider], source
        for name in ENV_KEYS.get(provider, ()):
            if self.environ.get(name):
                return self.environ[name], "environment"
        return "", "none"

    def public(self):
        with self.lock:
            profiles = {}
            for provider, profile in self.profiles.items():
                key, source = self._credential(provider)
                profiles[provider] = {"provider": provider, **profile, "has_key": bool(key), "key_source": source,
                                      "remembered": source == "saved", "ready": bool(profile["model"] and (key or not CATALOG[provider]["requires_key"]))}
            return {**profiles[self.provider], "providers": deepcopy(PROVIDERS), "profiles": profiles}

    def save(self, payload):
        with self.lock:
            provider = payload.get("provider", self.provider)
            if provider not in CATALOG:
                raise ValueError("Choose a listed model provider.")
            model = required_text(payload.get("model"), "Model ID", 100)
            endpoint = validate_endpoint(provider, payload.get("endpoint"))
            key = payload.get("api_key", "")
            if not isinstance(key, str) or len(key) > 8192 or any(c.isspace() for c in key.strip()):
                raise ValueError("Enter a valid API key without spaces.")
            remember = payload.get("remember_key", not key.strip() and provider in self.saved_keys)
            clear = payload.get("clear_key", False)
            if not isinstance(remember, bool) or not isinstance(clear, bool):
                raise ValueError("Key storage choices must be true or false.")
            if clear:
                self.session_keys.pop(provider, None)
                self.saved_keys.pop(provider, None)
                self._write("credentials.json", self.saved_keys)
            else:
                existing, source = self._credential(provider)
                entered = key.strip() or (existing if source in {"session", "saved"} else "")
                if entered and remember:
                    self.saved_keys[provider] = entered
                    self.session_keys.pop(provider, None)
                elif entered:
                    self.session_keys[provider] = entered
                    self.saved_keys.pop(provider, None)
                if entered:
                    self._write("credentials.json", self.saved_keys)
            self.profiles[provider] = {"model": model, "endpoint": endpoint}
            self.provider = provider
            self._write("model-settings.json", {"provider": self.provider, "profiles": self.profiles})
            return self.public()

    def resolve(self, model=None, provider=None):
        with self.lock:
            provider = provider or self.provider
            if provider not in CATALOG:
                raise ValueError("Choose a listed model provider.")
            key, _ = self._credential(provider)
            profile = self.profiles[provider]
            chosen = required_text(model if model is not None else profile["model"], "Model ID", 100)
            if CATALOG[provider]["requires_key"] and not key:
                raise ValueError("Add this provider's API key in Model settings before starting a model job.")
            return {"provider": provider, "model": chosen, "endpoint": profile["endpoint"], "api_key": key}

    def redacted(self, text, extra_keys=()):
        with self.lock:
            keys = list(self.session_keys.values()) + list(self.saved_keys.values()) + [self.environ.get(name, "") for names in ENV_KEYS.values() for name in names] + list(extra_keys)
        text = str(text)
        for key in sorted({key for key in keys if key}, key=len, reverse=True):
            text = text.replace(key, "[redacted key]")
        return text

    def test(self):
        from .llm import make_client
        config = self.resolve()
        client = make_client(config)
        result = client.chat.completions.create(model=config["model"], messages=[{"role": "system", "content": "Return only a JSON object, with no Markdown."}, {"role": "user", "content": 'Reply with {"ok":true}.'}], max_completion_tokens=512)
        try:
            reply = json.loads(result.choices[0].message.content)
        except (ValueError, TypeError, AttributeError, IndexError):
            raise ValueError("The model responded, but did not return the requested JSON. Choose a JSON-capable model before running the pipeline.") from None
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise ValueError("The model responded, but did not follow the short JSON test. Check the chosen model before a full run.")
        return {"ok": True, "message": "Connection and a short JSON response succeeded. This does not test the full pipeline or its large prompts.", "provider": config["provider"], "model": config["model"]}

    def models(self, payload):
        from .llm import list_models
        provider = payload.get("provider", self.provider)
        if provider not in CATALOG or CATALOG[provider]["kind"] != "local":
            raise ValueError("Model discovery is available for local servers.")
        with self.lock:
            key, _ = self._credential(provider)
            endpoint = validate_endpoint(provider, payload.get("endpoint", self.profiles[provider]["endpoint"]))
        return {"models": list_models({"provider": provider, "model": "", "endpoint": endpoint, "api_key": key})}
