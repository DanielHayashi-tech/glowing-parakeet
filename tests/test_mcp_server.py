import http.client
import io
import json
import threading
import unittest

from tests import _path  # noqa: F401
import mcp_server as server


def rpc(method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class ProtocolTests(unittest.TestCase):
    def test_initialize_echoes_a_supported_version_and_declares_only_tools(self):
        result = server.handle_message(rpc("initialize", {"protocolVersion": "2025-06-18"}))["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(list(result["capabilities"]), ["tools"])
        self.assertEqual(result["serverInfo"]["name"], "corre-cortes")
        self.assertIn("freshness.stale", result["instructions"])

    def test_initialize_with_an_unknown_version_gets_our_latest(self):
        result = server.handle_message(rpc("initialize", {"protocolVersion": "1999-01-01"}))["result"]
        self.assertEqual(result["protocolVersion"], server.SUPPORTED_PROTOCOLS[-1])

    def test_instructions_put_the_key_guidance_in_the_first_512_characters(self):
        self.assertLess(len(server.INSTRUCTIONS), 512)

    def test_notifications_get_no_response(self):
        self.assertIsNone(server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_ping(self):
        self.assertEqual(server.handle_message(rpc("ping"))["result"], {})

    def test_unknown_method_is_a_json_rpc_error(self):
        self.assertEqual(server.handle_message(rpc("resources/list"))["error"]["code"], -32601)

    def test_malformed_requests_are_rejected(self):
        self.assertEqual(server.handle_message({"id": 1})["error"]["code"], -32600)
        self.assertEqual(server.handle_message("nope")["error"]["code"], -32600)

    def test_batches_are_answered_and_notifications_dropped(self):
        out = server.handle_payload([rpc("ping", request_id=1), {"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertEqual([r["id"] for r in out], [1])


class ToolTests(unittest.TestCase):
    def test_exactly_one_tool_and_it_is_marked_read_only(self):
        tools = server.handle_message(rpc("tools/list"))["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["get_training_context"])
        annotations = tools[0]["annotations"]
        self.assertTrue(annotations["readOnlyHint"])
        self.assertFalse(annotations["destructiveHint"])
        self.assertFalse(annotations["openWorldHint"])
        self.assertFalse(tools[0]["inputSchema"]["additionalProperties"])

    def test_call_returns_structured_content_and_matching_text(self):
        result = server.handle_message(rpc("tools/call", {"name": "get_training_context", "arguments": {"recent_activities": 3}}))["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        for key in server.TOOL["outputSchema"]["required"]:
            self.assertIn(key, result["structuredContent"])
        self.assertLessEqual(len(result["structuredContent"]["recent_activities"]), 3)

    def test_call_with_no_arguments_uses_defaults(self):
        result = server.handle_message(rpc("tools/call", {"name": "get_training_context"}))["result"]
        self.assertFalse(result["isError"])

    def test_bad_arguments_come_back_as_a_tool_error_the_model_can_read(self):
        for bad in ({"recent_activities": 0}, {"recent_activities": 999}, {"recent_activities": "ten"}, {"recent_activities": True}, {"limit": 5}):
            result = server.handle_message(rpc("tools/call", {"name": "get_training_context", "arguments": bad}))["result"]
            self.assertTrue(result["isError"], bad)
            self.assertIn("text", result["content"][0])

    def test_unknown_tool_is_an_error(self):
        self.assertEqual(server.handle_message(rpc("tools/call", {"name": "delete_everything"}))["error"]["code"], -32602)

    def test_a_missing_database_gives_a_safe_message_not_a_stack_trace(self):
        original = server.DB_PATH
        server.DB_PATH = "does-not-exist.db"
        try:
            result = server.handle_message(rpc("tools/call", {"name": "get_training_context"}))["result"]
        finally:
            server.DB_PATH = original
        self.assertTrue(result["isError"])
        self.assertEqual(result["content"][0]["text"], "The training data is temporarily unavailable.")


class StdioTests(unittest.TestCase):
    def test_lines_in_lines_out_and_parse_errors_are_reported(self):
        stdin = io.StringIO("\n".join([json.dumps(rpc("ping")), "{not json", json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})]) + "\n")
        stdout = io.StringIO()
        server.serve_stdio(stdin, stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0], {"jsonrpc": "2.0", "id": 1, "result": {}})
        self.assertEqual(lines[1]["error"]["code"], -32700)
        self.assertEqual(len(lines), 2)       # the notification produced nothing


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_http_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path="/mcp", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = body if isinstance(body, (bytes, type(None))) else json.dumps(body)
        connection.request(method, path, body=payload, headers=headers or {"Content-Type": "application/json"})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, (json.loads(data) if data else None), response

    def test_it_only_listens_on_the_loopback_address(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_post_initialize(self):
        status, body, _ = self.request("POST", body=rpc("initialize", {"protocolVersion": "2025-06-18"}))
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["serverInfo"]["name"], "corre-cortes")

    def test_notification_is_accepted_with_202_and_no_body(self):
        status, body, _ = self.request("POST", body={"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((status, body), (202, None))

    def test_tool_call_over_http(self):
        status, body, _ = self.request("POST", body=rpc("tools/call", {"name": "get_training_context", "arguments": {"recent_activities": 2}}))
        self.assertEqual(status, 200)
        self.assertFalse(body["result"]["isError"])

    def test_only_post_is_allowed(self):
        for method in ("GET", "DELETE", "PUT"):
            status, _, response = self.request(method, body=None)
            self.assertEqual(status, 405, method)
            self.assertEqual(response.getheader("Allow"), "POST")

    def test_wrong_path_is_404(self):
        self.assertEqual(self.request("POST", path="/", body=rpc("ping"))[0], 404)

    def test_a_foreign_browser_origin_is_refused(self):
        headers = {"Content-Type": "application/json", "Origin": "https://evil.example"}
        self.assertEqual(self.request("POST", body=rpc("ping"), headers=headers)[0], 403)

    def test_a_local_origin_is_allowed(self):
        headers = {"Content-Type": "application/json", "Origin": "http://localhost:6274"}
        self.assertEqual(self.request("POST", body=rpc("ping"), headers=headers)[0], 200)

    def test_a_foreign_host_header_is_refused(self):
        headers = {"Content-Type": "application/json", "Host": "evil.example"}
        self.assertEqual(self.request("POST", body=rpc("ping"), headers=headers)[0], 403)

    def test_bad_json_and_oversized_bodies(self):
        self.assertEqual(self.request("POST", body=b"{nope")[0], 400)
        self.assertEqual(self.request("POST", body=b"x" * (server.MAX_BODY_BYTES + 1))[0], 413)


if __name__ == "__main__":
    unittest.main()
