"""Regression tests for the prototype protocol's safety boundaries."""

import asyncio
import json
import sys
import types
import unittest
from pathlib import Path

PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "quanyu_zhilian"
package = types.ModuleType("quanyu_zhilian")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules.setdefault("quanyu_zhilian", package)

from quanyu_zhilian.protocol import (  # noqa: E402
    GatewayError,
    GatewayProtocol,
    validate_components,
    validate_parameters,
)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 0.0
        self.published: list[tuple[str, dict]] = []
        self.protocol = GatewayProtocol(
            "cyd_aabbccddeeff",
            "pi-controller-01",
            "x" * 32,
            self.publish,
            lambda: None,
            clock=lambda: self.now,
        )
        self.protocol.broker_connected = True

    async def publish(self, suffix: str, payload: dict) -> None:
        self.published.append((suffix, payload))

    def telemetry(self, suffix="hello", **overrides) -> str:
        data = {
            "schema": "qyzl.cyd.prototype/1",
            "gateway_id": "cyd_aabbccddeeff",
            "boot_id": "0011223344556677",
            "sequence": 1,
            "uptime_ms": 20,
            "firmware": "0.1.0",
            "room": "Unassigned",
            "config_revision": 0,
            "controller_online": False,
            "wifi_rssi": -55,
            "free_heap": 1000,
            "min_free_heap": 900,
            "reset_reason": 1,
            "indicator": "off",
            "transport": "tls",
        }
        data.update(overrides)
        return json.dumps(data)

    async def handshake(self) -> None:
        self.protocol.feed("hello", self.telemetry(), False)
        await self.protocol.tick()
        config = self.published[-1][1]
        self.assertEqual(self.published[-1][0], "config")
        self.protocol.feed(
            "config_ack",
            json.dumps(
                {
                    "schema": "qyzl.cyd.prototype/1",
                    "gateway_id": "cyd_aabbccddeeff",
                    "boot_id": self.protocol.boot_id,
                    "sequence": 2,
                    "config_revision": config["config_revision"],
                    "error_code": "",
                    "persisted": False,
                }
            ),
            False,
        )
        self.assertTrue(self.protocol.ready)

    async def test_retained_or_wrong_identity_telemetry_never_marks_online(self):
        self.protocol.feed("state", self.telemetry(), True)
        self.assertFalse(self.protocol.online)
        self.protocol.feed("state", self.telemetry(gateway_id="cyd_000000000000"), False)
        self.assertFalse(self.protocol.online)
        self.protocol.feed("state", self.telemetry(boot_id="invalid"), False)
        self.assertFalse(self.protocol.online)

    async def test_live_state_after_retained_snapshot_starts_controller_sync(self):
        payload = self.telemetry(suffix="state", firmware="0.1.4")
        self.protocol.feed("state", payload, True)
        self.assertFalse(self.protocol.online)

        self.protocol.feed("state", payload, False)
        self.assertTrue(self.protocol.online)
        await self.protocol.tick()
        self.assertEqual([topic for topic, _ in self.published], ["controller", "config"])

    async def test_handshake_and_controller_heartbeat_sequence(self):
        await self.handshake()
        self.assertTrue(self.protocol.ready)
        await self.protocol.tick()
        heartbeats = [message for topic, message in self.published if topic == "controller"]
        self.assertEqual(heartbeats[0]["sequence"], 1)
        self.assertEqual(heartbeats[0]["session_id"], self.protocol.session_id)

    async def test_component_extension_discovers_state_and_validates_command(self):
        descriptor = {
            "id": "ir.receiver",
            "platform": "sensor",
            "name": "Last infrared signal",
            "state_key": "last_signal",
            "commands": [
                {
                    "id": "send_raw",
                    "action": "send_raw",
                    "name": "Send signal",
                    "parameters": [
                        {"name": "raw", "type": "integer_array", "min_items": 2, "max_items": 100},
                        {"name": "frequency_khz", "type": "integer", "min": 30, "max": 60},
                    ],
                }
            ],
        }
        payload = json.loads(self.telemetry("hello"))
        payload.update(component_model=1, components=[descriptor])
        self.assertTrue(self.protocol.feed("hello", json.dumps(payload), False))
        payload["sequence"] = 2
        payload["component_states"] = {
            "last_signal": {
                "value": "NEC",
                "attributes": {"bits": 32, "raw": [9000, 4500]},
            }
        }
        self.assertTrue(self.protocol.feed("state", json.dumps(payload), False))
        self.assertEqual(self.protocol.components["ir.receiver"]["platform"], "sensor")
        self.assertEqual(self.protocol.component_states["last_signal"]["value"], "NEC")
        command = self.protocol.components["ir.receiver"]["commands"]["send_raw"]
        self.assertEqual(
            validate_parameters(command, {"raw": [9000, 4500], "frequency_khz": 38}),
            {"raw": [9000, 4500], "frequency_khz": 38},
        )
        with self.assertRaisesRegex(GatewayError, "INVALID_ARGUMENT"):
            validate_parameters(command, {"raw": [9000], "frequency_khz": 99})

    async def test_invalid_component_descriptors_are_rejected(self):
        self.assertIsNone(validate_components(1, [{"id": "../unsafe"}]))
        self.assertIsNone(validate_components(2, []))
        self.assertIsNone(validate_components(True, []))

    async def test_generic_component_command_uses_advertised_action(self):
        await self.handshake()
        self.protocol.components = validate_components(
            1,
            [
                {
                    "id": "ir.transmitter",
                    "platform": "button",
                    "name": "Infrared transmitter",
                    "state_key": "tx_state",
                    "commands": [
                        {
                            "id": "send_raw",
                            "action": "module.ir.send",
                            "name": "Send raw signal",
                            "parameters": [
                                {"name": "raw", "type": "integer_array", "min_items": 2},
                                {"name": "frequency_khz", "type": "integer", "min": 30, "max": 60},
                            ],
                        }
                    ],
                }
            ],
        )
        task = asyncio.create_task(
            self.protocol.command(
                "send_raw",
                target="ir.transmitter",
                command_id="send_raw",
                parameters={"raw": [9000, 4500], "frequency_khz": 38},
            )
        )
        await asyncio.sleep(0)
        command = self.published[-1][1]
        self.assertEqual(command["target"], "ir.transmitter")
        self.assertEqual(command["action"], "module.ir.send")
        self.assertEqual(command["parameters"]["raw"], [9000, 4500])
        self.protocol.feed(
            "ack",
            json.dumps(
                {
                    "schema": "qyzl.cyd.prototype/1",
                    "gateway_id": "cyd_aabbccddeeff",
                    "boot_id": self.protocol.boot_id,
                    "sequence": 3,
                    "session_id": self.protocol.session_id,
                    "command_id": command["command_id"],
                    "result": "executed",
                    "error_code": "",
                    "indicator": "off",
                    "confidence": "transmitted_only",
                }
            ),
            False,
        )
        await task

    async def test_command_waits_for_correlated_ack_and_never_replays(self):
        await self.handshake()
        task = asyncio.create_task(self.protocol.command("set_indicator", "green"))
        await asyncio.sleep(0)
        topic, command = self.published[-1]
        self.assertEqual(topic, "cmd")
        self.assertFalse(command.get("retain", False))
        self.assertEqual(command["parameters"], {"color": "green"})
        self.protocol.feed(
            "ack",
            json.dumps(
                {
                    "schema": "qyzl.cyd.prototype/1",
                    "gateway_id": "cyd_aabbccddeeff",
                    "boot_id": self.protocol.boot_id,
                    "sequence": 3,
                    "session_id": self.protocol.session_id,
                    "command_id": command["command_id"],
                    "result": "executed",
                    "error_code": "",
                    "indicator": "green",
                    "confidence": "output_level_only",
                }
            ),
            False,
        )
        await task
        self.assertEqual(len([topic for topic, _ in self.published if topic == "cmd"]), 1)

    async def test_timeout_reports_unknown_and_does_not_replay(self):
        await self.handshake()
        with self.assertRaisesRegex(GatewayError, "RESULT_UNKNOWN"):
            await self.protocol.command("set_indicator", "blue", ack_timeout=0.001)
        self.assertEqual(len([topic for topic, _ in self.published if topic == "cmd"]), 1)

    async def test_room_change_invalidates_readiness_until_ack(self):
        await self.handshake()
        self.protocol.set_room("客房 101")
        self.assertFalse(self.protocol.ready)
        self.assertEqual(self.protocol.configuration_error, None)
        await self.protocol.tick()
        self.assertEqual(self.published[-1][1]["room"], "客房 101")

    async def test_session_change_fails_pending_command(self):
        await self.handshake()
        task = asyncio.create_task(self.protocol.command("set_indicator", "red"))
        await asyncio.sleep(0)
        self.protocol.connection_changed(False)
        with self.assertRaisesRegex(GatewayError, "RESULT_UNKNOWN"):
            await task

    async def test_old_session_ack_cannot_complete_command(self):
        await self.handshake()
        task = asyncio.create_task(self.protocol.command("set_indicator", "red", ack_timeout=0.01))
        await asyncio.sleep(0)
        command = self.published[-1][1]
        self.protocol.feed(
            "ack",
            json.dumps(
                {
                    "schema": "qyzl.cyd.prototype/1",
                    "gateway_id": "cyd_aabbccddeeff",
                    "boot_id": self.protocol.boot_id,
                    "sequence": 3,
                    "session_id": "old-session",
                    "command_id": command["command_id"],
                    "result": "executed",
                    "error_code": "",
                    "indicator": "red",
                }
            ),
            False,
        )
        with self.assertRaisesRegex(GatewayError, "RESULT_UNKNOWN"):
            await task

    async def test_stale_status_is_unavailable_then_new_session_recovers(self):
        await self.handshake()
        session = self.protocol.session_id
        self.now = 31
        self.assertFalse(self.protocol.online)
        await self.protocol.tick()
        self.protocol.feed("state", self.telemetry(sequence=4), False)
        self.assertTrue(self.protocol.online)
        self.assertFalse(self.protocol.ready)
        self.assertNotEqual(session, self.protocol.session_id)
        await self.protocol.tick()
        heartbeats = [data for topic, data in self.published if topic == "controller"]
        self.assertEqual(heartbeats[-1]["sequence"], 1)

    async def test_boot_change_drops_pending_command(self):
        await self.handshake()
        task = asyncio.create_task(self.protocol.command("set_indicator", "red"))
        await asyncio.sleep(0)
        self.protocol.feed("hello", self.telemetry(boot_id="8899aabbccddeeff"), False)
        with self.assertRaisesRegex(GatewayError, "RESULT_UNKNOWN"):
            await task
        self.assertFalse(self.protocol.ready)
        self.assertEqual(self.protocol.boot_id, "8899aabbccddeeff")

    async def test_long_utf8_room_blocks_controls_and_config_publish(self):
        await self.handshake()
        self.protocol.set_room("房" * 11)
        self.assertEqual(self.protocol.configuration_error, "ROOM_TOO_LONG")
        self.assertFalse(self.protocol.ready)
        count = len(self.published)
        await self.protocol.tick()
        self.assertEqual(len(self.published), count)
        with self.assertRaisesRegex(GatewayError, "GATEWAY_NOT_READY"):
            await self.protocol.command("set_indicator", "green")

    async def test_invalid_or_duplicate_state_cannot_extend_freshness(self):
        await self.handshake()
        self.now = 29
        self.protocol.feed("state", self.telemetry(sequence=1), False)
        self.protocol.feed("state", self.telemetry(sequence=3, free_heap=True), False)
        self.now = 31
        self.assertFalse(self.protocol.online)

    async def test_unknown_schema_is_rejected_but_new_firmware_is_accepted(self):
        self.protocol.feed("hello", self.telemetry(schema="qyzl.gateway/1"), False)
        self.assertFalse(self.protocol.online)
        self.protocol.feed("hello", self.telemetry(firmware="99.0"), False)
        self.assertTrue(self.protocol.online)

    async def test_broker_reconnect_reserves_revision_against_old_config_ack(self):
        await self.handshake()
        revision = self.protocol.revision
        self.protocol.connection_changed(False)
        self.protocol.connection_changed(True)
        self.protocol.feed("state", self.telemetry(sequence=4), False)
        self.protocol.feed(
            "config_ack",
            json.dumps(
                {
                    "schema": "qyzl.cyd.prototype/1",
                    "gateway_id": "cyd_aabbccddeeff",
                    "boot_id": self.protocol.boot_id,
                    "sequence": 5,
                    "config_revision": revision,
                    "error_code": "",
                    "persisted": False,
                }
            ),
            False,
        )
        self.assertFalse(self.protocol.ready)

    async def test_unload_fails_waiter_and_rejects_new_commands(self):
        await self.handshake()
        task = asyncio.create_task(self.protocol.command("request_diagnostics"))
        await asyncio.sleep(0)
        self.protocol.close()
        with self.assertRaisesRegex(GatewayError, "RESULT_UNKNOWN"):
            await task
        with self.assertRaisesRegex(GatewayError, "GATEWAY_NOT_READY"):
            await self.protocol.command("request_diagnostics")


if __name__ == "__main__":
    unittest.main()
