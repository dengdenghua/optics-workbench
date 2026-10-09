"""Protocol boundary tests plus isolated real-core subprocess workflows."""
import io
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from optics_workbench.mcp_server import (
    LEGACY_VERSIONS, MAX_MESSAGE_BYTES, META_CAPABILITIES, META_VERSION,
    MCPServer, MODERN_VERSION, TOOLS,
)


def request(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def modern(method, params=None, request_id=1, version=MODERN_VERSION):
    parameters = dict(params or {})
    parameters["_meta"] = {META_VERSION: version, META_CAPABILITIES: {}}
    return request(method, parameters, request_id)


def initialize(server, version="2025-11-25"):
    reply = server.handle(request("initialize", {"protocolVersion": version,
         "capabilities": {}, "clientInfo": {"name": "unit-test", "version": "1"}}))
    assert "result" in reply, reply
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return reply


def tool(name, args=None, request_id=2):
    return request("tools/call", {"name": name, "arguments": args or {}}, request_id)


def unpack(reply):
    result = reply["result"]
    return json.loads(result["content"][0]["text"])["data"]


def scene_fixture():
    """Synthetic unfolded meridional scene, never loaded from a personal project."""
    return {"schema_version": 1, "units": "mm", "elements": [
        {"id": "source", "kind": "source", "label": "演示光源", "z_mm": 0,
         "y_mm": 0, "aperture_mm": 1, "width_mm": 1},
        {"id": "lens", "kind": "lens", "label": "薄透镜符号", "z_mm": 20,
         "y_mm": 0, "aperture_mm": 10, "width_mm": 2, "focal_mm": 20},
        {"id": "screen", "kind": "screen", "label": "目标面", "z_mm": 40,
         "y_mm": 0, "aperture_mm": 10, "width_mm": 1}],
        "rays": {"half_angle_deg": 5, "rays_per_point": 5,
                 "source_points": 3, "wavelength_nm": 550}}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.wb = Mock()
        self.wb.stats.return_value = {"mode": "demo"}
        self.server = MCPServer(self.wb)

    def test_legacy_versions_negotiate_and_require_ready(self):
        for version in LEGACY_VERSIONS:
            server = MCPServer(self.wb)
            self.assertEqual(server.handle(tool("optics_stats"))["error"]["code"], -32602)
            self.assertEqual(initialize(server, version)["result"]["protocolVersion"], version)
            self.assertEqual(unpack(server.handle(tool("optics_stats"))), {"mode": "demo"})

    def test_unrecognized_legacy_version_returns_supported_version(self):
        self.assertEqual(initialize(self.server, "2099-01-01")["result"]["protocolVersion"], LEGACY_VERSIONS[0])

    def test_initialization_validation_does_not_change_state(self):
        self.assertEqual(self.server.handle(request("initialize", {"protocolVersion": "x"}))["error"]["code"], -32602)
        self.assertIsNone(self.server.legacy_version)
        initialize(self.server)
        self.assertEqual(self.server.handle(request("initialize"))["error"]["code"], -32600)

    def test_modern_discovery_then_stateless_call(self):
        reply = self.server.handle(modern("server/discover"))
        result = reply["result"]
        self.assertIn(MODERN_VERSION, result["supportedVersions"])
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["cacheScope"], "private")
        self.assertIn("io.modelcontextprotocol/serverInfo", result["_meta"])
        fresh = MCPServer(self.wb)
        reply = fresh.handle(modern("tools/call", {"name": "optics_stats"}))
        self.assertEqual(unpack(reply), {"mode": "demo"})
        self.assertEqual(reply["result"]["structuredContent"], {"data": {"mode": "demo"}})
        self.assertFalse(fresh.initialized)

    def test_modern_each_request_requires_metadata(self):
        self.server.handle(modern("server/discover"))
        self.assertEqual(self.server.handle(request("tools/list"))["error"]["code"], -32602)
        incomplete = request("tools/list", {"_meta": {META_VERSION: MODERN_VERSION}})
        self.assertEqual(self.server.handle(incomplete)["error"]["code"], -32602)
        self.assertEqual(self.server.handle(modern("ping"))["error"]["code"], -32601)

    def test_modern_unsupported_version(self):
        error = self.server.handle(modern("server/discover", version="2099-01-01"))["error"]
        self.assertEqual(error["code"], -32022)
        self.assertIn(MODERN_VERSION, error["data"]["supported"])

    def test_modern_identity_is_validated_but_not_used_as_authorization(self):
        invalid = modern("tools/list")
        invalid["params"]["_meta"]["io.modelcontextprotocol/clientInfo"] = "operator"
        self.assertEqual(self.server.handle(invalid)["error"]["code"], -32602)
        supplied = modern("tools/list")
        supplied["params"]["_meta"]["io.modelcontextprotocol/clientInfo"] = {"name": "arbitrary-client", "version": "1"}
        self.assertIn("tools", self.server.handle(supplied)["result"])

    def test_dual_era_does_not_reuse_modern_capabilities(self):
        initialize(self.server, "2024-11-05")
        reply = self.server.handle(modern("tools/list"))
        self.assertEqual(reply["result"]["resultType"], "complete")
        legacy = self.server.handle(tool("optics_stats"))
        self.assertNotIn("resultType", legacy["result"])
        self.assertNotIn("structuredContent", legacy["result"])

    def test_catalog_deterministic_and_correct_mutation_annotations(self):
        result = self.server.handle(modern("tools/list"))["result"]
        names = [t["name"] for t in result["tools"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(set(names)))
        readonly = MCPServer(self.wb, read_only=True)
        tools = readonly.handle(modern("tools/list"))["result"]["tools"]
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in tools))
        denied = readonly.handle(modern("tools/call", {"name": "optics_create_prototype"}))
        self.assertEqual(denied["error"]["code"], -32602)
        self.wb.new_project.assert_not_called()

    def test_protocol_errors_are_not_tool_execution_errors(self):
        initialize(self.server)
        cases = [(request("unknown/method"), -32601),
                 (tool("unknown_tool"), -32602),
                 (request("tools/call", {"name": "optics_stats", "arguments": []}), -32602),
                 (request("tools/list", {"cursor": "bad"}), -32602),
                 (request("tools/call", {"name": "optics_stats", "task": {}}), -32602)]
        for payload, code in cases:
            self.assertEqual(self.server.handle(payload)["error"]["code"], code)

    def test_argument_validation_cannot_call_core(self):
        initialize(self.server)
        for args in ({"page": True}, {"page": 0}, {"page": "2"}, {"limit": 101}, {"query": 3}, {"path": "not-an-accepted-argument"}):
            reply = self.server.handle(tool("optics_search_documents", args))
            self.assertTrue(reply["result"]["isError"])
        self.wb.library.assert_not_called()
        self.assertTrue(self.server.handle(tool("optics_save_prototype", {"project": []}))["result"]["isError"])
        self.wb.save_project.assert_not_called()

    def test_scene_argument_validation_prevents_core_calls(self):
        cases = [
            ("optics_get_scene", {}, "scene"),
            ("optics_get_scene", {"project_id": ""}, "scene"),
            ("optics_trace_scene", {"scene": []}, "preview_scene"),
            ("optics_save_scene", {"project_id": "p", "version": True, "scene": {}}, "save_scene"),
            ("optics_save_scene", {"project_id": "p", "version": 0, "scene": {}}, "save_scene"),
            ("optics_save_scene", {"project_id": "p", "version": "1", "scene": {}}, "save_scene"),
            ("optics_save_scene", {"project_id": "p", "scene": {}}, "save_scene"),
            ("optics_apply_design", {"project_id": "p", "version": 1, "parameter_updates": []}, "apply_design"),
            ("optics_apply_design", {"project_id": "p", "version": 1, "scene": None}, "apply_design"),
            ("optics_apply_design", {"project_id": "p", "version": 1, "note": "x" * 2001}, "apply_design"),
            ("optics_apply_design", {"project_id": "p", "version": 1, "path": "unaccepted"}, "apply_design"),
        ]
        for name, args, method in cases:
            with self.subTest(tool=name, arguments=args):
                wb = Mock()
                reply = MCPServer(wb).handle(modern("tools/call", {"name": name, "arguments": args}))
                self.assertTrue(reply["result"]["isError"])
                getattr(wb, method).assert_not_called()

    def test_read_only_scene_tools_are_visible_but_mutations_cannot_execute(self):
        server = MCPServer(self.wb, read_only=True)
        names = {t["name"] for t in server.handle(modern("tools/list"))["result"]["tools"]}
        self.assertTrue({"optics_get_scene", "optics_trace_scene"} <= names)
        for name in ("optics_save_scene", "optics_apply_design"):
            self.assertNotIn(name, names)
            reply = server.handle(modern("tools/call", {"name": name, "arguments": {
                "project_id": "p", "version": 1, "scene": scene_fixture()}}))
            self.assertEqual(reply["error"]["code"], -32602)
        self.wb.save_scene.assert_not_called()
        self.wb.apply_design.assert_not_called()
        self.wb.preview_scene.return_value = {"kind": "paraxial_ray_fan"}
        reply = server.handle(modern("tools/call", {"name": "optics_trace_scene", "arguments": {"scene": scene_fixture()}}))
        self.assertEqual(unpack(reply)["kind"], "paraxial_ray_fan")

    def test_core_validation_and_internal_errors(self):
        initialize(self.server)
        self.wb.save_project.side_effect = ValueError("version conflict")
        result = self.server.handle(tool("optics_save_prototype", {"project": {}}))["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["content"][0]["text"], "version conflict")
        self.wb.stats.side_effect = RuntimeError("sensitive details")
        reply = self.server.handle(tool("optics_stats"))
        self.assertEqual(reply["error"]["code"], -32603)
        self.assertNotIn("sensitive details", json.dumps(reply))

    def test_all_adapters_route_to_contract_methods(self):
        cases = [
            ("optics_list_color_cases", {}, "color_cases", (), {}),
            ("optics_get_color_case", {"case_id":"demo"}, "color_case", ("demo",), {}),
            ("optics_get_color_budget", {"project_id":"p1"}, "color_budget", ("p1",), {}),
            ("optics_calculate_color_budget", {"budget":{}}, "calculate_color", ({},), {}),
            ("optics_save_color_budget", {"project_id":"p1","version":2,"budget":{}}, "save_color", ("p1",2,{}), {}),
            ("optics_stats", {}, "stats", (), {}),
            ("optics_sync_knowledge", {}, "sync", (), {}),
            ("optics_search_documents", {"query": "lens", "limit": 2}, "library", (), {"query": "lens", "limit": 2}),
            ("optics_get_document", {"source_id": "doc1"}, "document", ("doc1",), {}),
            ("optics_search_components", {"kind": "prisms"}, "components", (), {"kind": "prisms"}),
            ("optics_search_knowledge", {"query": "TIR"}, "knowledge", (), {"query": "TIR"}),
            ("optics_get_reference", {"slug": "tir.md"}, "reference", ("tir.md",), {}),
            ("optics_search_models", {"limit": 5}, "models", (), {"limit": 5}),
            ("optics_list_prototypes", {}, "projects", (), {}),
            ("optics_get_prototype", {"project_id": "p1"}, "project", ("p1",), {}),
            ("optics_get_scene", {"project_id": "p1"}, "scene", ("p1",), {}),
            ("optics_trace_scene", {"scene": scene_fixture()}, "preview_scene", (scene_fixture(),), {}),
            ("optics_save_scene", {"project_id": "p1", "version": 2, "scene": scene_fixture()}, "save_scene", ("p1", 2, scene_fixture()), {}),
            ("optics_apply_design", {"project_id": "p1", "version": 2, "scene": scene_fixture(), "parameter_updates": {"source_lumens": 800}, "note": "试验起点"},
             "apply_design", ("p1", 2), {"scene": scene_fixture(), "parameter_updates": {"source_lumens": 800}, "note": "试验起点"}),
            ("optics_create_prototype", {"template": "compact"}, "new_project", (), {"template": "compact"}),
            ("optics_calculate_budget", {"project": {"parameters": {}}}, "calculate", ({"parameters": {}},), {}),
            ("optics_save_prototype", {"project": {"version": 1}}, "save_project", ({"version": 1},), {}),
            ("optics_export_prototype", {"project_id": "p1"}, "export_project", ("p1",), {}),
            ("optics_import_prototype", {"payload": {"schema_version": 1}}, "import_project", ({"schema_version": 1},), {}),
        ]
        self.assertEqual({c[0] for c in cases}, {t["name"] for t in TOOLS})
        for name, args, method, positional, keywords in cases:
            wb = Mock()
            getattr(wb, method).return_value = {"ok": name}
            reply = MCPServer(wb).handle(modern("tools/call", {"name": name, "arguments": args}))
            self.assertEqual(unpack(reply), {"ok": name})
            getattr(wb, method).assert_called_once_with(*positional, **keywords)

    def test_notifications_never_mutate_or_reply(self):
        initialize(self.server)
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "optics_sync_knowledge"}}))
        self.wb.sync.assert_not_called()
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}))

    def test_invalid_ids_and_batches(self):
        for payload in ([], None, True, {"jsonrpc": "2.0", "method": "ping", "id": True},
                        {"jsonrpc": "2.0", "method": "ping", "id": None},
                        {"jsonrpc": "2.0", "method": "ping", "id": 1.5}):
            self.assertEqual(self.server.handle(payload)["error"]["code"], -32600)

    def test_stdio_utf8_bad_input_limit_and_recovery(self):
        inputs = [b'{bad}\n', b'\xff\n', b'{"x":NaN}\n', b'{"x":1e999}\n',
                  b'{"x":1,"x":2}\n', b'x' * (MAX_MESSAGE_BYTES + 1) + b'\n',
                  json.dumps(modern("tools/call", {"name": "optics_stats"}), ensure_ascii=False).encode() + b'\n']
        self.wb.stats.return_value = {"name": "光学\n预算"}
        output = io.BytesIO()
        self.server.serve(io.BytesIO(b''.join(inputs)), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(replies), 7)
        self.assertEqual([r["error"]["code"] for r in replies[:-1]], [-32700] * 5 + [-32600])
        self.assertEqual(unpack(replies[-1]), {"name": "光学\n预算"})

    def test_core_stdout_cannot_corrupt_protocol(self):
        def noisy():
            print("core diagnostic")
            return {"ok": True}
        self.wb.stats.side_effect = noisy
        output = io.BytesIO()
        line = json.dumps(modern("tools/call", {"name": "optics_stats"})).encode() + b'\n'
        self.server.serve(io.BytesIO(line), output)
        self.assertEqual(unpack(json.loads(output.getvalue())), {"ok": True})


class RealCoreMCPTests(unittest.TestCase):
    def test_scene_roundtrip_atomic_design_and_failed_write_leave_revision_unchanged(self):
        from optics_workbench.core import Workbench
        with tempfile.TemporaryDirectory() as data_dir:
            wb = Workbench(data_dir=data_dir)
            server = MCPServer(wb)
            initialize(server)
            project = unpack(server.handle(tool("optics_create_prototype", {"name": "场景往返"})))

            def call(name, arguments):
                reply = server.handle(tool(name, arguments))
                self.assertFalse(reply["result"].get("isError"), reply)
                return unpack(reply)

            envelope = call("optics_get_scene", {"project_id": project["id"]})
            self.assertEqual(envelope["version"], project["version"])
            self.assertEqual(envelope["trace"]["kind"], "paraxial_ray_fan")
            self.assertEqual(wb.project(project["id"]), project)
            scene = scene_fixture()
            trace = call("optics_trace_scene", {"scene": scene})
            self.assertEqual(trace["summary"]["launched"], 15)
            self.assertEqual(trace, call("optics_trace_scene", {"scene": scene}))
            for mutate in (
                lambda s: s["rays"].update(source_points=True),
                lambda s: s["rays"].update(half_angle_deg=16),
                lambda s: s["elements"][1].update(unsupported_field=1),
            ):
                invalid = copy.deepcopy(scene)
                mutate(invalid)
                rejected = server.handle(tool("optics_trace_scene", {"scene": invalid}))
                self.assertTrue(rejected["result"]["isError"], rejected)
                self.assertEqual(wb.project(project["id"]), project)
            saved = call("optics_save_scene", {"project_id": project["id"], "version": project["version"], "scene": scene})
            self.assertEqual(saved["scene"], scene)
            self.assertEqual(saved["version"], project["version"] + 1)
            self.assertEqual(saved["parameters"], project["parameters"])
            changed = copy.deepcopy(scene)
            changed["elements"][1]["focal_mm"] = 30
            applied = call("optics_apply_design", {"project_id": saved["id"], "version": saved["version"],
                "scene": changed, "parameter_updates": {"source_lumens": 1200}, "note": "条件起算"})
            self.assertEqual(applied["version"], saved["version"] + 1)
            self.assertEqual(applied["scene"], changed)
            self.assertEqual(applied["parameters"]["source_lumens"], 1200)
            self.assertIn("条件起算", applied["notes"])
            with wb.connect() as db:
                revisions = db.execute("SELECT count(*) FROM project_revisions WHERE project_id=?", (project["id"],)).fetchone()[0]
            self.assertEqual(revisions, 3)
            invalid_scene = copy.deepcopy(changed)
            invalid_scene["elements"][1]["focal_mm"] = 0
            cases = [
                {"version": saved["version"], "scene": scene},
                {"version": applied["version"], "scene": invalid_scene},
                {"version": applied["version"], "scene": scene, "parameter_updates": {"source_lumens": -1}},
                {"version": applied["version"], "parameter_updates": {"not_a_parameter": 1}},
                {"version": applied["version"]},
            ]
            for arguments in cases:
                reply = server.handle(tool("optics_apply_design", {"project_id": project["id"], **arguments}))
                self.assertTrue(reply["result"]["isError"], reply)
                self.assertEqual(wb.project(project["id"]), applied)
            with wb.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM project_revisions WHERE project_id=?", (project["id"],)).fetchone()[0], revisions)
            legacy_save = copy.deepcopy(applied)
            legacy_save.pop("scene")
            preserved = call("optics_save_prototype", {"project": legacy_save})
            self.assertEqual(preserved["scene"], changed)
            exported = call("optics_export_prototype", {"project_id": preserved["id"]})
            self.assertEqual(exported["project"]["scene"], changed)
            self.assertNotIn(data_dir, json.dumps(exported))
            imported = call("optics_import_prototype", {"payload": exported})
            self.assertNotEqual(imported["id"], preserved["id"])
            self.assertEqual(imported["scene"], changed)
            self.assertEqual(imported["parameters"], preserved["parameters"])

    def test_scene_tools_through_stdio_subprocess(self):
        from optics_workbench.core import Workbench
        with tempfile.TemporaryDirectory() as data_dir:
            wb = Workbench(data_dir=data_dir)
            project = wb.new_project(name="隔离的场景传输")
            scene = scene_fixture()
            actions = [
                ("optics_get_scene", {"project_id": project["id"]}),
                ("optics_trace_scene", {"scene": scene}),
                ("optics_save_scene", {"project_id": project["id"], "version": 1, "scene": scene}),
                ("optics_apply_design", {"project_id": project["id"], "version": 2, "parameter_updates": {"source_lumens": 3210}}),
                ("optics_save_scene", {"project_id": project["id"], "version": 2, "scene": scene}),
                ("optics_get_scene", {"project_id": project["id"]}),
                ("optics_export_prototype", {"project_id": project["id"]}),
            ]
            messages = [modern("tools/call", {"name": name, "arguments": args}, request_id=i)
                        for i, (name, args) in enumerate(actions, 1)]
            env = dict(os.environ)
            for key in ("OPTICS_WORKBENCH_CONFIG", "OPTICS_WORKBENCH_DATA"):
                env.pop(key, None)
            completed = subprocess.run([sys.executable, "-B", "-m", "optics_workbench.mcp_server", "--data-dir", data_dir],
                input="".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages).encode("utf8"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                cwd=Path(__file__).resolve().parents[1], timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf8"))
            replies = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual([r["id"] for r in replies], list(range(1, 8)))
            self.assertEqual(unpack(replies[1])["kind"], "paraxial_ray_fan")
            self.assertEqual(unpack(replies[2])["scene"], scene)
            self.assertEqual(unpack(replies[3])["version"], 3)
            self.assertTrue(replies[4]["result"]["isError"])
            self.assertEqual(unpack(replies[5])["version"], 3)
            self.assertEqual(unpack(replies[6])["project"]["scene"], scene)
            self.assertEqual(unpack(replies[6])["project"]["parameters"]["source_lumens"], 3210)

    def test_temp_database_prototype_roundtrip_and_conflict(self):
        from optics_workbench.core import Workbench
        with tempfile.TemporaryDirectory() as data_dir:
            wb = Workbench(data_dir=data_dir)
            server = MCPServer(wb)
            initialize(server)
            project = unpack(server.handle(tool("optics_create_prototype", {"name": "便携演示"})))
            project["parameters"]["source_lumens"] = 1200
            calculation = unpack(server.handle(tool("optics_calculate_budget", {"project": project})))
            self.assertEqual(calculation["kind"], "analytical_budget")
            saved = unpack(server.handle(tool("optics_save_prototype", {"project": project})))
            self.assertEqual(saved["version"], project["version"] + 1)
            self.assertTrue(server.handle(tool("optics_save_prototype", {"project": project}))["result"]["isError"])
            exported = unpack(server.handle(tool("optics_export_prototype", {"project_id": saved["id"]})))
            self.assertNotIn(data_dir, json.dumps(exported))
            imported = unpack(server.handle(tool("optics_import_prototype", {"payload": exported})))
            self.assertNotEqual(imported["id"], saved["id"])
            self.assertEqual(imported["parameters"], saved["parameters"])
            self.assertEqual(imported["calculation"]["input_hash"], saved["calculation"]["input_hash"])

    def test_module_stdio_subprocess_and_eof(self):
        messages = [modern("server/discover", request_id=1), modern("tools/list", request_id=2),
                    modern("tools/call", {"name": "optics_stats"}, request_id=3),
                    modern("tools/call", {"name": "optics_create_prototype", "arguments": {"name": "Unicode 光学"}}, request_id=4)]
        with tempfile.TemporaryDirectory() as data_dir:
            env = dict(os.environ)
            for name in ("OPTICS_WORKBENCH_CONFIG", "OPTICS_WORKBENCH_DATA"):
                env.pop(name, None)
            completed = subprocess.run([sys.executable, "-m", "optics_workbench.mcp_server", "--data-dir", data_dir],
                input="".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages).encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                cwd=Path(__file__).resolve().parents[1], timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
            replies = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4])
            self.assertEqual(unpack(replies[2])["mode"], "demo")
            self.assertEqual(unpack(replies[3])["name"], "Unicode 光学")
            self.assertTrue((Path(data_dir) / "workbench.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
