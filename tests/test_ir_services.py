"""Exercise local catalogue -> HA action handler -> protocol -> correlated ACK.

HA registration is stubbed; protocol, catalogue, schemas and action code are real.
Install voluptuous to run these tests; no live HA or broker is claimed.
"""

import asyncio
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "quanyu_zhilian"
package = types.ModuleType("quanyu_zhilian")
package.__path__ = [str(COMPONENT)]
sys.modules.setdefault("quanyu_zhilian", package)
HAS_VOLUPTUOUS = importlib.util.find_spec("voluptuous") is not None

from quanyu_zhilian.ir_library import InfraredLibrary  # noqa: E402
from quanyu_zhilian.protocol import GatewayProtocol, validate_components  # noqa: E402


@unittest.skipUnless(HAS_VOLUPTUOUS, "Install voluptuous for HA action harness")
class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE profiles(id TEXT, category TEXT, brand TEXT, model TEXT,
                    path TEXT, signal_count INTEGER, search_text TEXT, source_text BLOB);
                CREATE TABLE signals(profile_id TEXT, ordinal INTEGER, data BLOB);
                CREATE TABLE metadata(key TEXT, value TEXT);
                INSERT INTO profiles VALUES('test', 'TVs', 'Example', 'TV', 'TVs/Example.ir', 2, 'Example', NULL);
            """)
            for i, record in enumerate([
                {"name": "Power", "type": "raw", "frequency": "38000", "duty_cycle": "0.5", "data": "9000 4500 560 560"},
                {"name": "Power parsed", "type": "parsed", "protocol": "NECext", "address": "20 9F 00 00", "command": "11 00 80 00"},
                {"name": "Unsupported", "type": "parsed", "protocol": "Kaseikyo", "address": "78 02 20 03", "command": "C0 00 00 00"},
            ]):
                db.execute("INSERT INTO signals VALUES (?, ?, ?)", ("test", i, zlib.compress(json.dumps(record).encode())))
        db.close()

        modules = {name: types.ModuleType(name) for name in (
            "homeassistant", "homeassistant.core", "homeassistant.exceptions",
            "homeassistant.helpers", "homeassistant.helpers.config_validation",
        )}
        class HAError(Exception):
            pass
        self.HAError = HAError
        modules["homeassistant.core"].HomeAssistant = object
        modules["homeassistant.core"].ServiceCall = object
        modules["homeassistant.core"].SupportsResponse = types.SimpleNamespace(ONLY="only")
        modules["homeassistant.exceptions"].HomeAssistantError = HAError
        modules["homeassistant.helpers.config_validation"].string = str
        spec = importlib.util.spec_from_file_location("quanyu_zhilian.ir_services_harness", COMPONENT / "ir_services.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        self.sent = []

        async def publish(suffix, payload):
            self.sent.append((suffix, payload))
            self.protocol.feed("ack", json.dumps({
                "schema": "qyzl.cyd.prototype/1", "gateway_id": self.protocol.gateway_id,
                "boot_id": self.protocol.boot_id, "sequence": len(self.sent),
                "session_id": self.protocol.session_id, "command_id": payload["command_id"],
                "result": "executed", "error_code": "", "indicator": "off", "confidence": "transmitted_only",
            }), False)

        self.protocol = GatewayProtocol("cyd_aabbccddeeff", "test-controller", "x" * 32, publish, lambda: None, clock=lambda: 0)
        self.protocol.broker_connected = True
        self.protocol.configured = True
        self.protocol.last_seen = 0
        self.protocol.boot_id = "0011223344556677"
        self.protocol.components = validate_components(1, [{
            "id": "custom.transmitter", "platform": "sensor", "name": "Transmitter", "state_key": "signal",
            "commands": [{"id": "transmit", "action": "ir.send_raw", "name": "Send", "parameters": [
                {"name": "raw", "type": "integer_array", "min_items": 2, "max_items": 500},
                {"name": "frequency_khz", "type": "integer", "min": 30, "max": 60},
                {"name": "duty_cycle", "type": "integer", "min": 20, "max": 50},
            ]}, {"id": "parsed", "action": "ir.send_parsed", "name": "Send parsed", "parameters": [
                {"name": "protocol", "type": "string"},
                {"name": "address", "type": "integer", "min": 0, "max": 65535},
                {"name": "command", "type": "integer", "min": 0, "max": 65535},
                {"name": "bits", "type": "integer", "min": 1, "max": 64},
                {"name": "vendor_data", "type": "integer", "required": False, "min": 0, "max": 4294967295},
            ]}],
        }])
        self.actions = {}
        def register(domain, name, handler, **kwargs):
            self.actions[name] = (handler, kwargs["schema"])
        async def executor(method, *args):
            return await asyncio.to_thread(method, *args)
        gateway = types.SimpleNamespace(protocol=self.protocol, async_command=self.protocol.command)
        self.hass = types.SimpleNamespace(
            data={"quanyu_zhilian": {self.protocol.gateway_id: gateway}},
            services=types.SimpleNamespace(has_service=lambda domain, name: name in self.actions, async_register=register),
            async_add_executor_job=executor,
        )
        with patch.object(module, "InfraredLibrary", return_value=InfraredLibrary(self.path)):
            module.register_ir_services(self.hass)

    async def call(self, action, **data):
        handler, schema = self.actions[action]
        return await handler(types.SimpleNamespace(data=schema(data)))

    async def test_search_inspect_send_without_network_or_fixed_component_id(self):
        capabilities = await self.call("ir_gateways")
        self.assertTrue(capabilities["gateways"][0]["ir_raw_send"])
        self.assertTrue(capabilities["gateways"][0]["ir_parsed_send"])
        result = await self.call("ir_search", query="Example")
        self.assertEqual(result["profiles"][0]["id"], "test")
        result = await self.call("ir_inspect", profile_id="test")
        self.assertTrue(result["signals"][0]["cyd_sendable"])
        self.assertFalse(result["signals"][1]["cyd_sendable"])
        await self.call("ir_send", gateway_id=self.protocol.gateway_id, profile_id="test", signal_index=0)
        self.assertEqual(len(self.sent), 1)
        suffix, payload = self.sent[0]
        self.assertEqual(suffix, "cmd")
        self.assertEqual(payload["target"], "custom.transmitter")
        self.assertEqual(payload["action"], "ir.send_raw")
        self.assertEqual(payload["parameters"], {"raw": [9000, 4500, 560, 560], "frequency_khz": 38, "duty_cycle": 50})
        self.assertEqual(self.protocol.last_command_result, "transmitted_only")

        await self.call("ir_send", gateway_id=self.protocol.gateway_id, profile_id="test", signal_index=1)
        _, payload = self.sent[-1]
        self.assertEqual(payload["action"], "ir.send_parsed")
        self.assertEqual(payload["target"], "custom.transmitter")
        self.assertEqual(payload["parameters"], {
            "protocol": "NECEXT", "address": 0x9F20, "command": 0x8011, "bits": 32,
        })

    async def test_invalid_or_offline_calls_publish_nothing(self):
        with self.assertRaisesRegex(self.HAError, "UNSUPPORTED_PARSED_PROTOCOL"):
            await self.call("ir_send", gateway_id=self.protocol.gateway_id, profile_id="test", signal_index=2)
        with self.assertRaisesRegex(self.HAError, "Unknown gateway"):
            await self.call("ir_send", gateway_id="missing", profile_id="test", signal_index=0)
        self.assertEqual(self.sent, [])
