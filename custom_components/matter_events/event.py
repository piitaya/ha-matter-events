"""Press and rotation event entities for Matter switches."""

from dataclasses import dataclass
from typing import Any, cast

from chip.clusters import Objects as clusters
from matter_server.client import MatterClient
from matter_server.client.models.node import MatterEndpoint, MatterNode
from matter_server.common.models import EventType, MatterNodeEvent, ServerInfoMessage

from homeassistant.components.event import (
    ButtonEventType,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.components.matter.const import (
    DOMAIN as MATTER_DOMAIN,
    ID_TYPE_DEVICE_ID,
)
from homeassistant.components.matter.helpers import get_device_id, get_matter
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LOGGER

SwitchFeature = clusters.Switch.Bitmaps.Feature
SwitchEvents = clusters.Switch.Events

NAMESPACE_COMMON_POSITION = 0x08
TAG_COLUMN = 0x06
NAMESPACE_SWITCHES = 0x43
TAG_UP = 0x03
TAG_DOWN = 0x04
TAG_CUSTOM = 0x08

EVENT_TYPE_INITIAL_PRESS = "initial_press"
EVENT_TYPE_SWITCH_LATCHED = "switch_latched"
EVENT_TYPE_ROTATION = "rotation"
CLOCKWISE = "clockwise"
COUNTER_CLOCKWISE = "counter_clockwise"


@dataclass
class RotaryLayer:
    """The two Switch endpoints of one layer of a scroll wheel."""

    layer: str
    clockwise: MatterEndpoint
    counter_clockwise: MatterEndpoint | None


def _tags(endpoint: MatterEndpoint) -> list[tuple[Any, Any, str]]:
    tag_list = endpoint.get_attribute_value(
        None, clusters.Descriptor.Attributes.TagList
    )
    if not isinstance(tag_list, list):
        return []
    return [
        (
            getattr(tag, "namespaceID", None),
            getattr(tag, "tag", None),
            label if isinstance(label := getattr(tag, "label", None), str) else "",
        )
        for tag in tag_list
    ]


def _has_tag(endpoint: MatterEndpoint, namespace: int, tag: int) -> bool:
    return any(t[0] == namespace and t[1] == tag for t in _tags(endpoint))


def _column(endpoint: MatterEndpoint) -> str:
    return next(
        (
            t[2]
            for t in _tags(endpoint)
            if t[0] == NAMESPACE_COMMON_POSITION and t[1] == TAG_COLUMN
        ),
        "",
    )


def _is_rotary(endpoint: MatterEndpoint) -> bool:
    return any(
        t[0] == NAMESPACE_SWITCHES
        and t[1] == TAG_CUSTOM
        and t[2].casefold() == "rotary"
        for t in _tags(endpoint)
    )


def _switch_endpoints(node: MatterNode) -> list[MatterEndpoint]:
    return [
        endpoint
        for endpoint in node.endpoints.values()
        if endpoint.has_cluster(clusters.Switch)
    ]


def _rotary_layers(node: MatterNode) -> list[RotaryLayer]:
    by_layer: dict[str, list[MatterEndpoint]] = {}
    for endpoint in _switch_endpoints(node):
        if _is_rotary(endpoint):
            by_layer.setdefault(_column(endpoint), []).append(endpoint)
    layers = []
    for layer, endpoints in sorted(by_layer.items()):
        up = [ep for ep in endpoints if _has_tag(ep, NAMESPACE_SWITCHES, TAG_UP)]
        down = [ep for ep in endpoints if _has_tag(ep, NAMESPACE_SWITCHES, TAG_DOWN)]
        if len(up) != 1:
            LOGGER.debug(
                "Node %s layer %r has no single clockwise endpoint", node.node_id, layer
            )
            continue
        layers.append(RotaryLayer(layer, up[0], down[0] if len(down) == 1 else None))
    return layers


def _device(
    hass: HomeAssistant, server_info: ServerInfoMessage, endpoint: MatterEndpoint
) -> tuple[str, dr.DeviceEntry | None]:
    """Return the device of the Matter switch entity of the endpoint."""
    device_id = get_device_id(server_info, endpoint)
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    switch_unique_id = (
        f"{device_id}-{endpoint.endpoint_id}-GenericSwitch-"
        f"{clusters.Switch.id}-{clusters.Switch.Attributes.CurrentPosition.attribute_id}"
    )
    if (
        (
            entity_id := entity_registry.async_get_entity_id(
                "event", MATTER_DOMAIN, switch_unique_id
            )
        )
        and (entry := entity_registry.async_get(entity_id))
        and entry.device_id
    ):
        return device_id, device_registry.async_get(entry.device_id)
    return device_id, device_registry.async_get_device(
        identifiers={(MATTER_DOMAIN, f"{ID_TYPE_DEVICE_ID}_{device_id}")}
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the button and rotary entities of the Matter switches."""
    client = get_matter(hass).matter_client
    server_info = cast(ServerInfoMessage, client.server_info)
    added: set[str | None] = set()

    @callback
    def _async_add_new_entities() -> None:
        entities: list[MatterSwitchEventEntity] = []
        for node in client.get_nodes():
            for layer in _rotary_layers(node):
                device_id, device = _device(hass, server_info, layer.clockwise)
                if device is not None:
                    entities.append(
                        MatterRotaryEventEntity(client, device_id, device, layer)
                    )
            for endpoint in _switch_endpoints(node):
                if _is_rotary(endpoint):
                    continue
                device_id, device = _device(hass, server_info, endpoint)
                if device is not None:
                    entities.append(
                        MatterButtonEventEntity(client, device_id, device, endpoint)
                    )
        new_entities = [
            e for e in entities if e.event_types and e.unique_id not in added
        ]
        added.update(e.unique_id for e in new_entities)
        if new_entities:
            async_add_entities(new_entities)

    @callback
    def _async_entity_registry_updated(
        event: Event[er.EventEntityRegistryUpdatedData],
    ) -> None:
        if event.data["action"] != "create":
            return
        registry_entry = er.async_get(hass).async_get(event.data["entity_id"])
        if (
            registry_entry is not None
            and registry_entry.platform == MATTER_DOMAIN
            and "-GenericSwitch-" in registry_entry.unique_id
        ):
            _async_add_new_entities()

    _async_add_new_entities()
    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _async_entity_registry_updated
        )
    )


class MatterSwitchEventEntity(EventEntity):
    """Event entity fed by the Switch events of some endpoints of a node."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        client: MatterClient,
        device: dr.DeviceEntry,
        node_id: int,
        endpoint_ids: set[int],
    ) -> None:
        """Initialize the entity."""
        self._client = client
        self.device_entry = device
        self._node_id = node_id
        self._endpoint_ids = endpoint_ids
        self._last_event_number: int | None = None

    async def async_added_to_hass(self) -> None:
        """Listen to the Switch events of the node."""
        self.async_on_remove(
            self._client.subscribe_events(
                callback=self._on_node_event,
                event_filter=EventType.NODE_EVENT,
                node_filter=self._node_id,
            )
        )

    @callback
    def _on_node_event(self, event: EventType, data: MatterNodeEvent) -> None:
        if (
            data.endpoint_id not in self._endpoint_ids
            or data.cluster_id != clusters.Switch.id
        ):
            return
        # events are delivered again after a resubscription
        if (
            self._last_event_number is not None
            and data.event_number <= self._last_event_number
        ):
            return
        self._last_event_number = data.event_number
        LOGGER.debug(
            "%s: endpoint %s event %s data %s",
            self.entity_id,
            data.endpoint_id,
            data.event_id,
            data.data,
        )
        self._handle_switch_event(data)

    def _handle_switch_event(self, data: MatterNodeEvent) -> None:
        raise NotImplementedError


class MatterButtonEventEntity(MatterSwitchEventEntity):
    """Standard button events of a Generic Switch endpoint."""

    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(
        self,
        client: MatterClient,
        device_id: str,
        device: dr.DeviceEntry,
        endpoint: MatterEndpoint,
    ) -> None:
        """Initialize the entity."""
        super().__init__(client, device, endpoint.node.node_id, {endpoint.endpoint_id})
        self._attr_unique_id = f"{device_id}-{endpoint.endpoint_id}-button"
        self._attr_translation_key = "button"
        self._attr_translation_placeholders = {
            "layer": _column(endpoint) or str(endpoint.endpoint_id)
        }
        features = int(
            endpoint.get_attribute_value(None, clusters.Switch.Attributes.FeatureMap)
            or 0
        )
        self._action_switch = bool(features & SwitchFeature.kActionSwitch)
        event_types: list[str] = []
        if features & SwitchFeature.kLatchingSwitch:
            event_types.append(EVENT_TYPE_SWITCH_LATCHED)
        elif features & SwitchFeature.kMomentarySwitch:
            event_types.append(
                EVENT_TYPE_INITIAL_PRESS
                if self._action_switch
                else ButtonEventType.PRESS_START
            )
            if features & SwitchFeature.kMomentarySwitchRelease:
                event_types.append(ButtonEventType.PRESS_END)
            if features & SwitchFeature.kMomentarySwitchLongPress:
                event_types += [
                    ButtonEventType.LONG_PRESS_START,
                    ButtonEventType.LONG_PRESS_END,
                ]
            if features & SwitchFeature.kMomentarySwitchMultiPress:
                event_types += [
                    ButtonEventType.SINGLE_PRESS,
                    ButtonEventType.MULTI_PRESS,
                ]
        self._attr_event_types = event_types

    def _handle_switch_event(self, data: MatterNodeEvent) -> None:
        event_data: dict[str, Any] = {}
        match data.event_id:
            case SwitchEvents.SwitchLatched.event_id:
                event_type = EVENT_TYPE_SWITCH_LATCHED
            case SwitchEvents.InitialPress.event_id:
                event_type = (
                    EVENT_TYPE_INITIAL_PRESS
                    if self._action_switch
                    else ButtonEventType.PRESS_START
                )
            case SwitchEvents.ShortRelease.event_id:
                event_type = ButtonEventType.PRESS_END
            case SwitchEvents.LongPress.event_id:
                event_type = ButtonEventType.LONG_PRESS_START
            case SwitchEvents.LongRelease.event_id:
                event_type = ButtonEventType.LONG_PRESS_END
            case SwitchEvents.MultiPressComplete.event_id:
                count = (data.data or {}).get("totalNumberOfPressesCounted")
                if not isinstance(count, int) or count < 1:
                    return
                if count == 1:
                    event_type = ButtonEventType.SINGLE_PRESS
                else:
                    event_type = ButtonEventType.MULTI_PRESS
                    event_data["press_count"] = count
            case _:
                return
        if event_type not in self.event_types:
            return
        self._trigger_event(event_type, event_data)
        self.async_write_ha_state()


class MatterRotaryEventEntity(MatterSwitchEventEntity):
    """Rotation of one layer of a scroll wheel."""

    _attr_event_types = [EVENT_TYPE_ROTATION]

    def __init__(
        self,
        client: MatterClient,
        device_id: str,
        device: dr.DeviceEntry,
        layer: RotaryLayer,
    ) -> None:
        """Initialize the entity."""
        self._directions = {layer.clockwise.endpoint_id: CLOCKWISE}
        if layer.counter_clockwise is not None:
            self._directions[layer.counter_clockwise.endpoint_id] = COUNTER_CLOCKWISE
        super().__init__(
            client, device, layer.clockwise.node.node_id, set(self._directions)
        )
        self._attr_unique_id = f"{device_id}-{layer.clockwise.endpoint_id}-rotary"
        self._attr_translation_key = "rotary"
        self._attr_translation_placeholders = {"layer": layer.layer}
        self._reported_counts: dict[int, int] = {}

    def _handle_switch_event(self, data: MatterNodeEvent) -> None:
        endpoint_id = data.endpoint_id
        event_data = data.data or {}
        match data.event_id:
            case SwitchEvents.MultiPressOngoing.event_id:
                count = event_data.get("currentNumberOfPressesCounted")
                complete = False
            case SwitchEvents.MultiPressComplete.event_id:
                count = event_data.get("totalNumberOfPressesCounted")
                complete = True
            case _:
                return
        reported = self._reported_counts.get(endpoint_id, 0)
        if isinstance(count, int) and (
            count < reported or (not complete and count == reported)
        ):
            reported = 0
        if complete:
            self._reported_counts.pop(endpoint_id, None)
        elif isinstance(count, int):
            self._reported_counts[endpoint_id] = count
        if not isinstance(count, int) or (steps := count - reported) <= 0:
            return
        self._trigger_event(
            EVENT_TYPE_ROTATION,
            {"direction": self._directions[endpoint_id], "steps": steps},
        )
        self.async_write_ha_state()
