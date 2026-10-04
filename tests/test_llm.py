"""Provider contract checks without network or a required SDK installation."""
import sys
import traceback
import types
import unittest
from unittest.mock import Mock, patch

from blackboard_workbench import llm


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"ok":true}'))],
            usage=types.SimpleNamespace(model_dump=lambda: {"total_tokens": 8}),
        )
        self.native = Mock()
        self.native.chat.completions.create.return_value = self.response
        self.sdk_class = Mock(return_value=self.native)
        self.sdk = types.ModuleType("openai")
        self.sdk.OpenAI = self.sdk_class
        self.module_patch = patch.dict(sys.modules, {"openai": self.sdk})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.cache_patch = patch.object(llm, "_NATIVE_OPENAI", None)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.messages = [{"role": "system", "content": "Return JSON."},
                         {"role": "user", "content": "Original upstream prompt."}]

    def config(self, provider="openai", **extra):
        return {"provider": provider, "model": "selected-model", "endpoint": "",
                "api_key": "secret-provider-key", **extra}

    def test_openai_preserves_request_messages_bound_and_usage(self):
        client = llm.make_client(self.config())
        response = client.chat.completions.create(
            model="upstream-default", messages=self.messages, max_completion_tokens=512)
        self.sdk_class.assert_called_once_with(
            api_key="secret-provider-key", base_url=llm.DEFAULT_ENDPOINTS["openai"],
            timeout=90, max_retries=0)
        self.native.chat.completions.create.assert_called_once_with(
            model="selected-model", messages=self.messages, max_completion_tokens=512)
        self.assertIs(self.response, response)
        self.assertEqual({"total_tokens": 8}, response.usage.model_dump())

    def test_other_provider_routes_bound_and_default_output_limit(self):
        for provider in ("anthropic", "gemini", "mistral", "ollama", "local"):
            with self.subTest(provider=provider):
                self.sdk_class.reset_mock()
                self.native.chat.completions.create.reset_mock()
                client = llm.make_client(self.config(provider))
                client.chat.completions.create(messages=self.messages, model="upstream-default")
                self.assertEqual(llm.DEFAULT_ENDPOINTS[provider], self.sdk_class.call_args.kwargs["base_url"])
                format_arg = {"response_format": llm.JSON_RESPONSE_FORMAT} if provider == "ollama" else {}
                self.native.chat.completions.create.assert_called_once_with(
                    model="selected-model", messages=self.messages, max_tokens=4096, **format_arg)
                self.native.chat.completions.create.reset_mock()
                client.chat.completions.create(messages=self.messages, max_completion_tokens=1500)
                self.native.chat.completions.create.assert_called_once_with(
                    model="selected-model", messages=self.messages, max_tokens=1500, **format_arg)

    def test_custom_local_endpoint_and_optional_credential(self):
        client = llm.make_client(self.config("local", endpoint="http://local-model:9000/v1", api_key=""))
        client.chat.completions.create(messages=self.messages)
        self.assertEqual("http://local-model:9000/v1", self.sdk_class.call_args.kwargs["base_url"])
        self.assertEqual("workbench-local", self.sdk_class.call_args.kwargs["api_key"])
        self.assertEqual(900, self.sdk_class.call_args.kwargs["timeout"])
        with self.assertRaisesRegex(ValueError, "Configure the anthropic API key"):
            llm.make_client(self.config("anthropic", api_key=""))

    def test_ollama_thinking_off_is_explicit_and_does_not_affect_other_providers(self):
        for provider in ("ollama", "openai", "local"):
            self.native.chat.completions.create.reset_mock()
            llm.make_client(self.config(provider, thinking="off")).chat.completions.create(messages=self.messages)
            request = self.native.chat.completions.create.call_args.kwargs
            if provider == "ollama":
                self.assertEqual("none", request["reasoning_effort"])
            else:
                self.assertNotIn("reasoning_effort", request)

    def test_empty_response_is_rejected_and_json_is_not_repaired(self):
        for response in (types.SimpleNamespace(choices=[]),
                         types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=None))]),
                         types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="  "))])):
            self.native.chat.completions.create.return_value = response
            with self.assertRaisesRegex(ValueError, "no response text"):
                llm.make_client(self.config()).chat.completions.create(messages=self.messages)
        self.response.choices[0].message.content = "```json\n{}\n```"
        self.native.chat.completions.create.return_value = self.response
        result = llm.make_client(self.config()).chat.completions.create(messages=self.messages)
        self.assertEqual("```json\n{}\n```", result.choices[0].message.content)

    def test_ollama_requires_parseable_object_or_array_without_repair(self):
        client = llm.make_client(self.config("ollama"))
        for content in ('[{"accepted": true}]', '{"ok": true}'):
            self.response.choices[0].message.content = content
            self.assertIs(self.response, client.chat.completions.create(messages=self.messages))
        for content in ("[{'accepted': True}]", '"a string"', '```json\n{}\n```'):
            self.response.choices[0].message.content = content
            with self.assertRaisesRegex(ValueError, "invalid structured JSON"):
                client.chat.completions.create(messages=self.messages)

    def test_truncated_and_filtered_responses_cannot_be_accepted_as_complete(self):
        for reason, message in (("length", "truncated at its output limit"),
                                ("content_filter", "blocked by a content filter")):
            with self.subTest(finish_reason=reason):
                self.response.choices[0].finish_reason = reason
                with self.assertRaisesRegex(ValueError, message):
                    llm.make_client(self.config()).chat.completions.create(messages=self.messages)

    def test_provider_errors_exclude_secret_body_and_traceback_cause(self):
        class ProviderError(Exception):
            status_code = 401
        self.native.chat.completions.create.side_effect = ProviderError(
            "secret-provider-key response body with private source data")
        try:
            llm.make_client(self.config("gemini")).chat.completions.create(messages=self.messages)
        except ValueError as exc:
            rendered = "".join(traceback.format_exception(exc))
            self.assertIn("authentication or permission denied; HTTP 401", str(exc))
            self.assertNotIn("secret-provider-key", rendered)
            self.assertNotIn("private source data", rendered)
        else:
            self.fail("The provider exception must be sanitized.")

    def test_models_are_sorted_filtered_deduplicated_and_bounded(self):
        self.native.models.list.return_value = types.SimpleNamespace(data=[
            types.SimpleNamespace(id="z-model"), types.SimpleNamespace(id="a-model"),
            types.SimpleNamespace(id="a-model"), types.SimpleNamespace(id=""),
            types.SimpleNamespace(id=None)])
        self.assertEqual([{"id": "a-model", "label": "a-model"},
                          {"id": "z-model", "label": "z-model"}],
                         llm.list_models(self.config("ollama", model="", api_key="")))
        self.native.models.list.return_value = types.SimpleNamespace(data=[
            types.SimpleNamespace(id=f"model-{index}") for index in range(700)])
        self.assertEqual(500, len(llm.list_models(self.config("local", model=""))))

    def test_model_listing_errors_are_sanitized(self):
        class APIConnectionError(Exception):
            pass
        self.native.models.list.side_effect = APIConnectionError("secret-provider-key private body")
        with self.assertRaisesRegex(ValueError, "connection failed") as caught:
            llm.list_models(self.config("local", model=""))
        self.assertNotIn("secret-provider-key", str(caught.exception))

    def test_upstream_patch_captures_native_sdk_and_ignores_constructor_sentinel(self):
        previous = llm.install_upstream_client(self.config("mistral"))
        self.assertIs(previous, self.sdk_class)
        # Both module-level imports and imports inside constructors get the facade.
        from openai import OpenAI
        client = OpenAI(api_key="upstream-sentinel", timeout=1, max_retries=7)
        client.chat.completions.create(model="different-upstream-default", messages=self.messages)
        self.sdk_class.assert_called_once_with(
            api_key="secret-provider-key", base_url=llm.DEFAULT_ENDPOINTS["mistral"],
            timeout=90, max_retries=0)
        self.assertEqual("selected-model", self.native.chat.completions.create.call_args.kwargs["model"])
        # Additional clients still use the captured native SDK, not recursive facades.
        llm.make_client(self.config("local"))
        self.assertEqual(2, self.sdk_class.call_count)
        self.sdk.OpenAI = previous


if __name__ == "__main__":
    unittest.main()
