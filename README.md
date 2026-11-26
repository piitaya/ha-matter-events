# Matter Events

Temporary custom integration that adds event entities to Matter buttons and scroll wheels, next to the ones of the Matter integration. It previews two changes planned for Home Assistant Core: standard button event types for Matter switches ([home-assistant/core#177101](https://github.com/home-assistant/core/pull/177101)) and a rotary event entity for scroll wheels such as the IKEA BILRESA. Remove it once they land in Core.

## Entities

**Press**, one per Generic Switch endpoint, with the standard button event types of Home Assistant:

| Matter event | Event type | Event data |
|---|---|---|
| Initial press | `press_start` (`initial_press` on action switches) | |
| Short release | `press_end` | |
| Long press | `long_press_start` | |
| Long release | `long_press_end` | |
| Multi-press complete, 1 press | `single_press` | |
| Multi-press complete, 2 presses or more | `multi_press` | `press_count` |
| Switch latched | `switch_latched` | |

**Rotation**, one per layer of a scroll wheel. Its only event type is `rotation`, with `direction` (`clockwise` or `counter_clockwise`) and `steps` (the number of detents) in the event data. Events are sent while the wheel turns, not only when it stops, and there is no limit on the number of detents.

The scroll wheel endpoints are found from their semantic tags, as the IKEA BILRESA reports them: `rotary` for the rotation endpoints, Up and Down for the direction, and the column label for the layer.

## Installation

Requires Home Assistant 2026.12 or later with the Matter integration set up.

1. Add this repository to the Marketplace and install **Matter Events**:

   [![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=piitaya&repository=ha-matter-events&category=integration)

2. Restart Home Assistant.
3. Add the integration:

   [![Open your Home Assistant instance and start setting up Matter Events.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=matter_events)

The entities are added to the devices of the Matter integration, also for devices added later.

## Example

Dim a light with the first layer of a scroll wheel, 5 % per detent:

```yaml
alias: Dim the living room light with the scroll wheel
triggers:
  - trigger: event.received
    target:
      entity_id: event.scroll_wheel_rotation_1
    options:
      event_type:
        - rotation
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room
    data:
      brightness_step_pct: >-
        {{ trigger.to_state.attributes.steps
           * (5 if trigger.to_state.attributes.direction == 'clockwise' else -5) }}
mode: parallel
```

## Limits

- The integration uses internal helpers of the Matter integration of Core, which can change in any release.
- A reload of the Matter integration needs a reload of Matter Events.
