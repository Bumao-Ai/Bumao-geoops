"""Contract tests for the OpenAI-compatible model runtime.

The provider below is a real local HTTP server, not a mocked response object:
the runtime must build the request, send it over a socket, and parse the JSON
reply. No test asserts a canned completion from the product itself.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from geoops.ai import ModelRuntime, ModelRuntimeError, model_chat_node
from geoops.api import AuditLog, PermissionPolicy, create_server
from geoops.domain import DomainRegistry
from geoops.workflow import NodeStatus, run


class _Provider(BaseHTTPRequestHandler):
    reply_text = "OK"
    status = 200
    port = 0
    last_path = ""
    last_auth = ""
    last_body = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        type(self).last_path = self.path
        type(self).last_auth = self.headers.get("Authorization") or ""
        try:
            type(self).last_body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            type(self).last_body = None
        if type(self).status != 200:
            body = json.dumps({"error": {"message": "bad credentials"}}).encode("utf-8")
            self.send_response(type(self).status)
        else:
            body = json.dumps(
                {
                    "model": "provider-model",
                    "choices": [{"message": {"content": type(self).reply_text}}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                }
            ).encode("utf-8")
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


_MODULE_SERVER = None


def setUpModule():
    global _MODULE_SERVER
    _MODULE_SERVER = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    _Provider.port = _MODULE_SERVER.server_address[1]
    threading.Thread(target=_MODULE_SERVER.serve_forever, daemon=True).start()


def tearDownModule():
    _MODULE_SERVER.shutdown()
    _MODULE_SERVER.server_close()


class ModelRuntimeTests(unittest.TestCase):
    def setUp(self):
        _Provider.reply_text = "OK"
        _Provider.status = 200
        _Provider.last_path = ""
        _Provider.last_auth = ""
        _Provider.last_body = None
        self.runtime = ModelRuntime(
            base_url="http://127.0.0.1:%d/v1" % _Provider.port,
            api_key="secret-key",
            model="provider-model",
        )

    def test_unconfigured_status_is_explicit(self):
        runtime = ModelRuntime()
        status = runtime.status()
        self.assertEqual(status["state"], "NOT_CONFIGURED")
        self.assertIn("GEOOPS_MODEL_BASE_URL", status["reason"])
        with self.assertRaises(ModelRuntimeError) as caught:
            runtime.invoke("hello")
        self.assertEqual(caught.exception.code, "NOT_CONFIGURED")

    def test_env_file_configures_a_real_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "model.env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# local operator file\n")
                handle.write("GEOOPS_MODEL_BASE_URL=http://127.0.0.1:%d/v1\n" % _Provider.port)
                handle.write("GEOOPS_MODEL_NAME=file-model\n")
                handle.write('GEOOPS_MODEL_API_KEY="file-secret"\n')
            with patch.dict(os.environ, {}, clear=True):
                runtime = ModelRuntime.from_env(path)
                status = runtime.status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["state"], "READY")
            self.assertEqual(status["model"], "file-model")
            self.assertEqual(status["authentication"], "bearer")
            self.assertEqual(status["config_file"], path)
            self.assertNotIn("file-secret", json.dumps(status))

    def test_environment_wins_over_the_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "model.env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("GEOOPS_MODEL_BASE_URL=http://file-host/v1\n")
                handle.write("GEOOPS_MODEL_NAME=file-model\n")
            with patch.dict(
                os.environ,
                {
                    "GEOOPS_MODEL_BASE_URL": "http://127.0.0.1:%d/v1" % _Provider.port,
                    "GEOOPS_MODEL_NAME": "environment-model",
                },
                clear=True,
            ):
                runtime = ModelRuntime.from_env(path)
                status = runtime.status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["model"], "environment-model")
            self.assertEqual(status["endpoint"], "http://127.0.0.1:%d/v1" % _Provider.port)

    def test_bad_env_file_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "model.env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("GEOOPS_UNKNOWN_SETTING=oops\n")
            with patch.dict(os.environ, {}, clear=True):
                runtime = ModelRuntime.from_env(path)
                status = runtime.status()
            self.assertFalse(status["configured"])
            self.assertEqual(status["state"], "CONFIG_ERROR")
            self.assertIn("unknown key", status["reason"])

    def test_invoke_sends_real_http_request(self):
        result = self.runtime.invoke("请回答 OK", system="你是测试助手", max_tokens=16)
        self.assertEqual(result["text"], "OK")
        self.assertEqual(result["model"], "provider-model")
        self.assertEqual(_Provider.last_path, "/v1/chat/completions")
        self.assertEqual(_Provider.last_auth, "Bearer secret-key")
        self.assertEqual(_Provider.last_body["model"], "provider-model")
        self.assertEqual(_Provider.last_body["messages"][0]["role"], "system")
        self.assertEqual(_Provider.last_body["messages"][1]["content"], "请回答 OK")

    def test_provider_error_is_reported_without_credentials(self):
        _Provider.status = 401
        with self.assertRaises(ModelRuntimeError) as caught:
            self.runtime.invoke("hello")
        self.assertEqual(caught.exception.code, "PROVIDER_HTTP_ERROR")
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertIn("bad credentials", str(caught.exception))
        self.assertNotIn("secret-key", str(caught.exception))

    def test_model_node_runs_inside_workflow(self):
        node = model_chat_node("M1", "模型原因", self.runtime, prompt="解释变化检测")
        workflow = run([node], {})
        self.assertEqual(workflow.status, NodeStatus.PASS)
        self.assertEqual(workflow.node_runs[0].output["text"], "OK")
        self.assertIn("provider-model", workflow.node_runs[0].detail)

    def test_model_node_without_runtime_is_error_not_fake_pass(self):
        node = model_chat_node("M2", "未配置模型", ModelRuntime(), prompt="hello")
        workflow = run([node], {})
        self.assertEqual(workflow.status, NodeStatus.ERROR)
        self.assertEqual(workflow.node_runs[0].status, NodeStatus.ERROR)
        self.assertIn("missing: GEOOPS_MODEL_BASE_URL", workflow.node_runs[0].detail)


class ModelRuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.registry = DomainRegistry()
        self.runtime = ModelRuntime(
            base_url="http://127.0.0.1:%d/v1" % _Provider.port,
            api_key="api-key",
            model="provider-model",
        )
        self.policy = PermissionPolicy({"admin": ["model:invoke"]})
        self.server = create_server(
            self.registry,
            policy=self.policy,
            audit=AuditLog(limit=100),
            model_runtime=self.runtime,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, token=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers["X-GeoOps-Token"] = token
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_status_is_public_and_probe_needs_token(self):
        status, payload = self.call("GET", "/api/v1/model-runtime")
        self.assertEqual(status, 200)
        self.assertTrue(payload["runtime"]["configured"])
        self.assertNotIn("api-key", json.dumps(payload))
        self.assertEqual(self.call("POST", "/api/v1/model-runtime/probe")[0], 401)
        self.assertEqual(self.call("POST", "/api/v1/model-runtime/probe", token="admin")[0], 200)

    def test_chat_returns_real_provider_text(self):
        status, payload = self.call(
            "POST", "/api/v1/model-runtime/chat",
            {"prompt": "请回答 OK"}, token="admin",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["text"], "OK")


if __name__ == "__main__":
    unittest.main()
