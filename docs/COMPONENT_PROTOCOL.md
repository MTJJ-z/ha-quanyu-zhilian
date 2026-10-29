# CYD Component Protocol Extension 1

This is an additive extension to `qyzl.cyd.prototype/1`. It keeps the existing
MQTT topics, identity envelope, sequence numbers, session, and ACK behavior.
An older gateway may omit the extension; its existing fixed entities continue
to work. A new gateway advertises `component_model: 1` and `components` in its
live `hello` message.

## Discovery

`components` is an array of at most 64 descriptors. Component IDs are stable
within a gateway and match `[a-z][a-z0-9_.-]{0,63}`. The allowed platforms are
`sensor`, `binary_sensor`, `switch`, `select`, and `button`.

```json
{
  "component_model": 1,
  "components": [
    {
      "id": "ir.receiver",
      "platform": "sensor",
      "name": "Last infrared signal",
      "state_key": "last_signal",
      "commands": []
    },
    {
      "id": "ir.capture",
      "platform": "button",
      "name": "Infrared capture",
      "state_key": "capture_state",
      "commands": [
        {"id": "start", "action": "receive_start", "name": "Start learning", "parameters": []},
        {"id": "stop", "action": "receive_stop", "name": "Stop learning", "parameters": []}
      ]
    }
  ]
}
```

Each descriptor has `id`, `platform`, `name`, `state_key`, and `commands`.
`state_key` is a unique key in the `state.component_states` object. `commands` contains at
most 16 entries, each with a stable `id`, firmware-defined `action`, display
`name`, and a `parameters` array. A parameter has `name`, `type`, optional
`required` (default true), and optional numeric `min`/`max`. Supported types
are `string`, `boolean`, `integer`, `number`, and `integer_array`; arrays may
also declare `min_items` and `max_items`.

Descriptors may also declare generic Home Assistant presentation metadata:
`icon`, `device_class`, `unit`, `state_class`, and `entity_category`. The latter
accepts `config` or `diagnostic`; sensor `state_class` accepts `measurement`,
`total`, or `total_increasing`. Device classes and units use Home Assistant's
standard string values for the selected platform.

Sensors report scalar `string`, `integer`, or finite `number` values (or null).
Binary sensors and switches report booleans. Selects report one of their
declared options. Buttons have no state value; their `state_key` may be omitted
by sending no corresponding state entry.

Switch and select descriptors additionally declare `control`:

```json
{"command_id":"set","value_parameter":"value"}
```

The referenced command must exist and have a required parameter named by
`value_parameter`; it must be boolean for a switch and string for a select.
Select descriptors also provide a non-empty `options` string array.

## State

The live `hello` advertises descriptors. Live `state` reports carry component
values as a map keyed by `state_key`. Each value is an object with a JSON scalar `value` and optional
JSON object `attributes`:

```json
{"component_states":{"last_signal":{"value":"NEC","attributes":{"bits":32,"frequency_khz":38,"raw":[9000,4500,560]}}}}
```

The integration validates IDs and values, limits the document to 64 KiB,
limits a component state to 8 KiB, and exposes attributes on the corresponding
Home Assistant entity. Missing values remain unknown; they are not inferred.

## Commands

All commands use the existing `cmd` topic and authenticated session envelope.
`target` is the component ID, `action` is the descriptor's firmware action,
and `parameters` is an object validated against that command's declared
parameter list. A switch/select entity uses its declared `control` mapping.
Buttons are generated for commands with no required parameters. Parameterized
commands are callable through the generic `quanyu_zhilian.execute` service:

```yaml
action: quanyu_zhilian.execute
data:
  gateway_id: cyd_08a570f3af48
  component_id: ir.transmitter
  command_id: send_raw
  parameters:
    raw: [9000, 4500, 560]
    frequency_khz: 38
```

The firmware remains responsible for mapping declared actions to hardware.
The integration does not contain peripheral-specific drivers or action logic.
The common ACK retains the base protocol's `indicator` field and returns a
non-empty, bounded `confidence` string; the latter is not restricted to a
fixed list so new component types can report their own evidence level.
