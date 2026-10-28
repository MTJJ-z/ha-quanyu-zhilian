"""Constants for the CYD prototype integration."""

DOMAIN = "quanyu_zhilian"
SCHEMA = "qyzl.cyd.prototype/1"
SUPPORTED_FIRMWARE = {"0.1.0", "0.1.1", "0.1.3", "0.1.4"}
TOPIC_ROOT = "qyzl/prototype/v1/gateway"
CONF_GATEWAY_ID = "gateway_id"
CONF_CONTROLLER_ID = "controller_id"
CONF_BINDING_TOKEN = "binding_token"
CONF_AREA_ID = "area_id"
COLORS = ("off", "red", "green", "blue")
IR_MAX_RAW = 100
IR_CAPTURE_EVENT = f"{DOMAIN}_ir_captured"
HEARTBEAT_SECONDS = 10
STALE_SECONDS = 30
COMMAND_TIMEOUT = 5
PROBE_TIMEOUT = 25
MAX_PENDING = 8
