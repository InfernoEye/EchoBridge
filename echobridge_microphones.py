"""Windows microphone selection via active WASAPI capture endpoints.

WASAPI enumerates Windows Core Audio endpoints in DEVICE_STATE_ACTIVE,
so it avoids disabled/disconnected input devices and the duplicates exposed
through MME/DirectSound/WDM-KS host APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class Microphone:
    label: str
    token: str
    index: int
    name: str


def _host_api_indices(sd):
    apis = sd.query_hostapis()
    indexes = [i for i, api in enumerate(apis)
               if "wasapi" in str(api.get("name", "")).casefold()]
    if not indexes:
        raise RuntimeError("Windows WASAPI audio support was not found. Try reinstalling sounddevice.")
    return indexes, apis


def active_microphones(sd):
    """Return each enabled Windows microphone once (WASAPI only).

    Index is resolved anew each time the user records. Token is independent
    of unrelated PortAudio numeric indexes; ordinal distinguishes identically
    named capture endpoints.
    """
    wasapi, _ = _host_api_indices(sd)
    microphones = []
    seen = {}
    for index, device in enumerate(sd.query_devices()):
        if device.get("hostapi") not in wasapi or int(device.get("max_input_channels", 0)) < 1:
            continue
        name = " ".join(str(device.get("name", "") or "").split())
        if not name:
            continue
        folded = name.casefold()
        seen[folded] = seen.get(folded, 0) + 1
        ordinal = seen[folded]
        token = f"wasapi:{quote(folded, safe='')}:{ordinal}"
        label = f"{name} ({ordinal})" if ordinal > 1 else name
        microphones.append(Microphone(label, token, index, name))
    return sorted(microphones, key=lambda mic: (mic.name.casefold(), mic.index))


def normalize_selection(sd, saved):
    """Convert old PortAudio numeric choices safely, or reset to default."""
    saved = str(saved or "default")
    devices = active_microphones(sd)
    if saved == "default" or any(mic.token == saved for mic in devices):
        return saved
    if saved.isdecimal():
        # Legacy numeric indexes are unsafe after any Windows device change.
        # Only migrate if the number currently identifies a WASAPI endpoint.
        for mic in devices:
            if mic.index == int(saved):
                return mic.token
    return "default"


def resolve_input(sd, selection):
    """Return (current PortAudio index, metadata), raising for unavailable mic."""
    selection = str(selection or "default")
    devices = active_microphones(sd)
    if not devices:
        raise RuntimeError("No enabled Windows microphones found. Enable a microphone in Windows Sound settings.")
    if selection == "default":
        wasapi, hostapis = _host_api_indices(sd)
        available = {mic.index for mic in devices}
        for api_id in wasapi:
            index = hostapis[api_id].get("default_input_device", -1)
            if index in available:
                return index, sd.query_devices(index, "input")
        raise RuntimeError("No default Windows microphone is configured. Select a microphone in EchoBridge settings.")
    for mic in devices:
        if mic.token == selection:
            return mic.index, sd.query_devices(mic.index, "input")
    raise RuntimeError("The selected microphone is no longer enabled or connected. Open Settings and select an active microphone.")
