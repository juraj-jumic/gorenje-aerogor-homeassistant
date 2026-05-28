#!/usr/bin/env python3
"""
Gorenje Aerogor Heat Pump → Home Assistant bridge — v2 with WRITES.

READ:  connects to USR-W600 SocketA (192.168.0.X:8899) and parses status
       broadcasts → publishes 22 sensors to MQTT with HA auto-discovery.

WRITE: subscribes to MQTT command topics; on incoming setpoint changes,
       constructs the proprietary 22-byte write frame (verified by
       reverse-engineering 6 captured cloud commands) and SENDS IT BACK
       to the W600 through the SAME SocketA TCP connection — which forwards
       bytes out the W600's serial port to the heat pump's controller.

Setpoint write requires NO cloud connection at all. Local. Direct.

Confirmed write parameter IDs (from cloud capture analysis):
  0x00 — System power (0.0=OFF, 1.0=ON)
  0x36 — DHW setpoint (°C, e.g. 33.0)
  0x78 — Heating-related toggle (0.0/1.0)

The DHW write was confirmed against status broadcasts: after sending
0x36 42.0, the config frame at offset 231 changed to 42.0.

⚠️  SAFETY: writes are sent verbatim to the heat pump controller. Wrong
values for some parameters may damage the unit. The three IDs above are
empirically known-safe (they're what the official app sends). Don't
write arbitrary parameter IDs without first confirming what they do.
"""

import argparse
import json
import logging
import os
import socket
import struct
import sys
import threading
import time

import paho.mqtt.client as mqtt  # pip install paho-mqtt

# ──────────────────────────────────────────────────────────────────────────
# CONFIG — defaults; can be overridden by CLI flags or env vars
# ──────────────────────────────────────────────────────────────────────────
W600_HOST    = os.environ.get("W600_HOST",   "192.168.0.50")
W600_PORT    = int(os.environ.get("W600_PORT", "8899"))
MQTT_HOST    = os.environ.get("MQTT_HOST",   "192.168.0.10")
MQTT_PORT    = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER    = os.environ.get("MQTT_USER",   "mqtt")
MQTT_PASS    = os.environ.get("MQTT_PASS",   "CHANGE_ME")
DEVICE_ID    = "aerogor"
DEVICE_NAME  = "Gorenje Aerogor"
PUBLISH_HZ   = 0.2
STATE_FILE   = os.environ.get("STATE_FILE", "/var/lib/aerogor/state.json")
SAVE_EVERY_S = 60  # how often to persist state to disk

# Watchdog: if the bridge hasn't published any state in this many seconds,
# the watchdog thread forcibly exits the process so systemd restarts it.
# 600 sec (10 min) is well past any normal quiet period — heat pump in deep
# standby still emits status frames every second.
WATCHDOG_TIMEOUT_S = 600

# Last successful publish timestamp (updated on every state publish).
# Watchdog thread monitors this and kills the process if it gets stale.
_last_publish_ts = 0.0

# ──────────────────────────────────────────────────────────────────────────
# Protocol
# ──────────────────────────────────────────────────────────────────────────
STATUS_HDR = b"\xB7\x00\x01\x00"
CONFIG_HDR = b"\x23\x02\x02\x00"
FRAME_LEN  = 198
CONFIG_LEN = 562
HDR_OFFSET = 10

# 10-byte device identifier in the write-frame prefix (constant in capture)
WRITE_PREFIX = bytes.fromhex("55AA01D8B04CF7B35A01")

# Status frame fields (read every 1 sec from the controller)
FIELDS = {
    35:  ("water_outlet",     "Water Outlet (Tuo)",     "°C",  "temperature", None),
    39:  ("water_return",     "Water Return (Tui)",     "°C",  "temperature", None),
    43:  ("indoor_coil",      "Indoor Coil (Tup)",      "°C",  "temperature", None),
    47:  ("dhw_tank",         "DHW Tank (TW)",          "°C",  "temperature", "mdi:water-thermometer"),
    51:  ("heating_water",    "Heating Water (TC)",     "°C",  "temperature", None),
    59:  ("room_temp",        "Room Temperature",       "°C",  "temperature", "mdi:home-thermometer"),
    63:  ("valve2_temp",      "Valve 2 Temp (Tv2)",     "°C",  "temperature", None),
    99:  ("compressor_hz",    "Compressor Frequency",   "Hz",  "frequency",   "mdi:sine-wave"),
    103: ("eev_opening",      "EEV Opening",            "P",   None,          "mdi:valve"),
    107: ("high_pressure",    "High Pressure (Pd)",     "bar", "pressure",    None),
    111: ("low_pressure",     "Low Pressure (Ps)",      "bar", "pressure",    None),
    115: ("ambient_temp",     "Ambient Temperature",    "°C",  "temperature", "mdi:thermometer"),
    119: ("line_status",      "Line Status",            "%",   None,          "mdi:gauge"),
    123: ("suction_temp",     "Suction Temp (Ts)",      "°C",  "temperature", None),
    127: ("outdoor_coil",     "Outdoor Coil (Tp)",      "°C",  "temperature", None),
    131: ("fan_speed",        "Fan Speed",              "rpm", None,          "mdi:fan"),
    139: ("compressor_amps",  "Compressor Current",     "A",   "current",     None),
    143: ("line_voltage",     "Line Voltage",           "V",   "voltage",     None),
    163: ("active_setpoint",  "Active Setpoint",        "°C",  "temperature", "mdi:thermometer-check"),
    167: ("sw_version",       "Software Version",       None,  None,          "mdi:chip"),
}
CONFIG_FIELDS = {
    231: ("dhw_setpoint",     "DHW Setpoint",           "°C",  "temperature", "mdi:water-boiler"),
    247: ("heating_setpoint", "Heating Water Setpoint", "°C",  "temperature", "mdi:radiator"),
    495: ("heating_curve",    "Heating Curve Move",     "°C",  "temperature", "mdi:chart-bell-curve-cumulative"),
}

# Mode is a single byte at offset 30 of the config frame, NOT a float
# Cloud API (setdata par4) uses values 0-4 for mode WRITES.
# The byte stored at offset 30 of the config frame is a DIFFERENT encoding —
# probably a flags byte. Known mappings:
MODE_OFFSET = 30
MODE_MAP = {
    # Confirmed by observed config frames after issuing each WRITE value:
    0x3F: "Standby",    # observed when in Standby
    0x40: "Auto",       # observed when in Auto
    # Heating / Cooling / DHW Only — bytes still unknown until user switches in.
    # The bridge will fall back to "Unknown(0xNN)" until those are added.
}

# Writable parameters (confirmed by reverse-engineering both local captures
# AND the cloud setdata API. cloud par(N) ↔ local protocol byte (N-1).)
WRITE_PARAMS = {
    "power":            (0x00, "bool",  0,    1,    "System Power",        None),    # cloud par1
    "mode":             (0x03, "int",   0,    4,    "Operating Mode",      None),    # cloud par4
    "dhw_setpoint":     (0x36, "float", 25.0, 75.0, "DHW Setpoint",        "°C"),    # cloud par55
    "heating_curve":    (0x78, "int",  -3,    3,    "Heating Curve Move",  "°C"),    # cloud par121
}

# Cloud-API-confirmed mode value mapping (setdata par4):
#   0 = Standby
#   1 = Heating
#   2 = Cooling
#   3 = Sanitary Hot Water (DHW Only)
#   4 = Auto
# Full 131-parameter dictionary in reference/aerogor_writable_params.md


# ──────────────────────────────────────────────────────────────────────────
# EXTENDED CONTROLS — additional useful writable parameters discovered via
# the cloud setdata API. All confirmed safe (these are what the official
# myheatpump.com web UI exposes to users).
#
# Mapping rules (empirically confirmed):
#   - WRITE: local_byte = cloud_par_number - 1
#   - READ:  config frame stores par_N as a little-endian float at
#            offset (11 + N*4)
# The READ formula is extrapolated from 2 known points (par55→231,
# par121→495). May be inexact for some parameters; verify by writing a
# distinctive value and watching the next config frame in MQTT.
# ──────────────────────────────────────────────────────────────────────────
EXTENDED_WRITES = [
    # ─── Switches (boolean ON/OFF toggles) ───────────────────────────
    {"key": "heating_curve_enable",   "local_byte": 0x17,   # par24
     "type": "switch", "name": "Heating Curve Enable",
     "icon": "mdi:chart-bell-curve",
     "config_offset": 11 + 24*4},
    {"key": "vacation_mode",          "local_byte": 0x2C,   # par45
     "type": "switch", "name": "Vacation Mode",
     "icon": "mdi:beach",
     "config_offset": 11 + 45*4},
    {"key": "reheating_enable",       "local_byte": 0x3F,   # par64
     "type": "switch", "name": "DHW Reheating",
     "icon": "mdi:water-boiler-alert",
     "config_offset": 11 + 64*4},
    {"key": "quiet_mode",             "local_byte": 0x4F,   # par80
     "type": "switch", "name": "Quiet Operation",
     "icon": "mdi:volume-mute",
     "config_offset": 11 + 80*4},
    {"key": "legionella_enable",      "local_byte": 0x28,   # par41
     "type": "switch", "name": "Anti-Legionella Program",
     "icon": "mdi:bacteria",
     "config_offset": 11 + 41*4},

    # ─── Numbers (sliders) ───────────────────────────────────────────
    {"key": "amb_start_heating",      "local_byte": 0x0A,   # par11
     "type": "number", "name": "Ambient Temp. to Start Heating",
     "min": -10, "max": 25, "step": 1, "unit": "°C",
     "icon": "mdi:thermometer-low",
     "config_offset": 11 + 11*4},
    {"key": "amb_start_cooling",      "local_byte": 0x0B,   # par12
     "type": "number", "name": "Ambient Temp. to Start Cooling",
     "min": 8, "max": 53, "step": 1, "unit": "°C",
     "icon": "mdi:thermometer-high",
     "config_offset": 11 + 12*4},
    {"key": "cooling_setpoint",       "local_byte": 0x16,   # par23
     "type": "number", "name": "Cooling Water Setpoint",
     "min": 7, "max": 30, "step": 1, "unit": "°C",
     "icon": "mdi:snowflake-thermometer",
     "config_offset": 11 + 23*4},
    {"key": "heating_no_curve",       "local_byte": 0x25,   # par38
     "type": "number", "name": "Heating Setpoint (no curve)",
     "min": 20, "max": 60, "step": 1, "unit": "°C",
     "icon": "mdi:radiator",
     "config_offset": 11 + 38*4},
    {"key": "legionella_setpoint",    "local_byte": 0x29,   # par42
     "type": "number", "name": "Anti-Legionella Setpoint",
     "min": 60, "max": 80, "step": 1, "unit": "°C",
     "icon": "mdi:bacteria-outline",
     "config_offset": 11 + 42*4},
    {"key": "reheating_setpoint",     "local_byte": 0x40,   # par65
     "type": "number", "name": "DHW Reheating Setpoint",
     "min": 25, "max": 55, "step": 1, "unit": "°C",
     "icon": "mdi:water-boiler",
     "config_offset": 11 + 65*4},
]

# Inject extended writes' config_offsets into CONFIG_FIELDS so the bridge
# also reads their current values from incoming config frames.
for _ew in EXTENDED_WRITES:
    _off = _ew["config_offset"]
    if _off not in CONFIG_FIELDS:
        _unit = _ew.get("unit")
        _dev_class = "temperature" if _unit == "°C" else None
        CONFIG_FIELDS[_off] = (
            _ew["key"],
            _ew["name"] + " (state)",
            _unit, _dev_class, _ew.get("icon"),
        )

log = logging.getLogger("aerogor")


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def build_write_frame(param_id: int, value: float) -> bytes:
    """Construct the 22-byte write frame for a parameter."""
    msg = bytearray()
    msg += WRITE_PREFIX                   # 10 bytes
    msg += bytes([0x07, 0x00, 0x05])      # type, 00, subtype
    msg += bytes([param_id, 0x00])        # param ID + 1 byte padding
    msg += struct.pack("<f", float(value))  # 4-byte LE float
    crc = crc16_modbus(msg[2:])           # CRC over [2:19] (everything except the 55 AA prefix)
    msg += crc.to_bytes(2, "little")
    msg += bytes([0x3A])                  # terminator
    return bytes(msg)


def parse_frame(frame: bytes, fields: dict) -> dict:
    out = {}
    for off, (fid, _, unit, _, _) in fields.items():
        if off + 4 > len(frame): continue
        v = struct.unpack_from("<f", frame, off)[0]
        if unit == "°C" and not -50 <= v <= 150: continue
        if unit == "bar" and not 0 <= v <= 60:   continue
        if unit == "V"  and not 100 <= v <= 300: continue
        if unit == "A"  and not 0 <= v <= 100:   continue
        if unit == "Hz" and not 0 <= v <= 200:   continue
        if unit == "rpm" and not 0 <= v <= 5000: continue
        out[fid] = round(v, 2) if unit in ("°C", "bar") else round(v)
    # For config frames, also extract mode byte
    if fields is CONFIG_FIELDS and len(frame) > MODE_OFFSET:
        mode_byte = frame[MODE_OFFSET]
        out["mode_raw"] = mode_byte
        out["mode_name"] = MODE_MAP.get(mode_byte, f"Unknown(0x{mode_byte:02X})")
    return out


def publish_discovery(client: mqtt.Client) -> None:
    device = {
        "identifiers": [DEVICE_ID],
        "name": DEVICE_NAME,
        "manufacturer": "Gorenje (Heatstar OEM)",
        "model": "Aerogor 7AS",
    }
    # Sensors
    for off, (fid, name, unit, dev_class, icon) in {**FIELDS, **CONFIG_FIELDS}.items():
        cfg = {
            "name": name, "unique_id": f"{DEVICE_ID}_{fid}",
            "state_topic": f"{DEVICE_ID}/state",
            "value_template": "{{ value_json." + fid + " }}",
            "device": device,
            "availability_topic": f"{DEVICE_ID}/availability",
        }
        if unit:       cfg["unit_of_measurement"] = unit
        if dev_class:  cfg["device_class"] = dev_class
        if icon:       cfg["icon"] = icon
        client.publish(f"homeassistant/sensor/{DEVICE_ID}/{fid}/config",
                       json.dumps(cfg), retain=True)

    # Writable controls — DHW setpoint as a "number" entity
    p_id, p_type, p_min, p_max, p_name, p_unit = WRITE_PARAMS["dhw_setpoint"]
    client.publish(
        f"homeassistant/number/{DEVICE_ID}/dhw_setpoint_ctrl/config",
        json.dumps({
            "name": p_name, "unique_id": f"{DEVICE_ID}_dhw_setpoint_ctrl",
            "command_topic": f"{DEVICE_ID}/cmd/dhw_setpoint",
            "state_topic":   f"{DEVICE_ID}/state",
            "value_template": "{{ value_json.dhw_setpoint }}",
            "min": p_min, "max": p_max, "step": 1, "mode": "slider",
            "unit_of_measurement": p_unit, "device": device,
            "availability_topic": f"{DEVICE_ID}/availability",
            "icon": "mdi:water-boiler",
        }),
        retain=True,
    )

    # Heating Curve Parallel Move (-3 to +3)
    p_id, _, p_min, p_max, p_name, p_unit = WRITE_PARAMS["heating_curve"]
    client.publish(
        f"homeassistant/number/{DEVICE_ID}/heating_curve_ctrl/config",
        json.dumps({
            "name": p_name, "unique_id": f"{DEVICE_ID}_heating_curve_ctrl",
            "command_topic": f"{DEVICE_ID}/cmd/heating_curve",
            "state_topic":   f"{DEVICE_ID}/state",
            "value_template": "{{ value_json.heating_curve }}",
            "min": p_min, "max": p_max, "step": 1, "mode": "slider",
            "unit_of_measurement": p_unit, "device": device,
            "availability_topic": f"{DEVICE_ID}/availability",
            "icon": "mdi:chart-bell-curve-cumulative",
        }),
        retain=True,
    )

    # Operating Mode select
    client.publish(
        f"homeassistant/select/{DEVICE_ID}/mode_ctrl/config",
        json.dumps({
            "name": "Operating Mode", "unique_id": f"{DEVICE_ID}_mode_ctrl",
            "command_topic": f"{DEVICE_ID}/cmd/mode",
            "state_topic":   f"{DEVICE_ID}/state",
            "value_template": "{{ value_json.mode_name | default('Unknown') }}",
            "options": ["Standby", "Heating", "Cooling", "DHW Only", "Auto"],
            "device": device,
            "availability_topic": f"{DEVICE_ID}/availability",
            "icon": "mdi:state-machine",
        }),
        retain=True,
    )

    # Power as a switch
    client.publish(
        f"homeassistant/switch/{DEVICE_ID}/power_ctrl/config",
        json.dumps({
            "name": "Heat Pump Power", "unique_id": f"{DEVICE_ID}_power_ctrl",
            "command_topic": f"{DEVICE_ID}/cmd/power",
            "payload_on": "ON", "payload_off": "OFF",
            "device": device,
            "availability_topic": f"{DEVICE_ID}/availability",
            "icon": "mdi:power",
        }),
        retain=True,
    )
    log.info("Published HA discovery: %d sensors + %d controls",
             len(FIELDS) + len(CONFIG_FIELDS), len(WRITE_PARAMS))

    # ─── Extended writable controls (auto-generated from EXTENDED_WRITES) ──
    for ew in EXTENDED_WRITES:
        key       = ew["key"]
        local     = ew["local_byte"]
        ent_type  = ew["type"]
        ent_name  = ew["name"]
        icon      = ew.get("icon")
        value_template = "{{ value_json." + key + " | default('') }}"

        if ent_type == "switch":
            cfg = {
                "name": ent_name,
                "unique_id": f"{DEVICE_ID}_{key}_ctrl",
                "command_topic": f"{DEVICE_ID}/cmd/{key}",
                "state_topic":   f"{DEVICE_ID}/state",
                "value_template":
                    "{% if value_json." + key + " | float(0) > 0.5 %}ON"
                    "{% else %}OFF{% endif %}",
                "payload_on": "ON", "payload_off": "OFF",
                "state_on": "ON",   "state_off": "OFF",
                "device": device,
                "availability_topic": f"{DEVICE_ID}/availability",
            }
            if icon: cfg["icon"] = icon
            client.publish(
                f"homeassistant/switch/{DEVICE_ID}/{key}_ctrl/config",
                json.dumps(cfg), retain=True,
            )

        elif ent_type == "number":
            cfg = {
                "name": ent_name,
                "unique_id": f"{DEVICE_ID}_{key}_ctrl",
                "command_topic": f"{DEVICE_ID}/cmd/{key}",
                "state_topic":   f"{DEVICE_ID}/state",
                "value_template": value_template,
                "min": ew["min"], "max": ew["max"],
                "step": ew.get("step", 1),
                "mode": "slider",
                "device": device,
                "availability_topic": f"{DEVICE_ID}/availability",
            }
            if ew.get("unit"): cfg["unit_of_measurement"] = ew["unit"]
            if icon: cfg["icon"] = icon
            client.publish(
                f"homeassistant/number/{DEVICE_ID}/{key}_ctrl/config",
                json.dumps(cfg), retain=True,
            )

    log.info("Published %d extended controls", len(EXTENDED_WRITES))


# Shared TCP socket — both reader and writer share it
_sock_lock = threading.Lock()
_sock: socket.socket | None = None


def open_w600() -> socket.socket:
    global _sock
    # 30 sec connect timeout — long enough for slow Wi-Fi reassociation,
    # short enough that watchdog kicks in if something is truly hung.
    s = socket.create_connection((W600_HOST, W600_PORT), timeout=30)
    # Enable TCP keepalive so genuinely dead connections are detected by the OS
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # Linux-specific: probe after 60s idle, then every 10s, give up after 5 probes
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
    except (AttributeError, OSError):
        pass  # not on Linux, or kernel doesn't expose these
    log.info("Connected to W600 %s:%d", W600_HOST, W600_PORT)
    _sock = s
    return s


def send_write(param_id: int, value: float) -> None:
    """Build write frame and send it through the shared W600 socket."""
    frame = build_write_frame(param_id, value)
    with _sock_lock:
        if _sock is None:
            log.error("Cannot write: W600 socket not connected")
            return
        try:
            _sock.sendall(frame)
            log.info("→ SENT param=0x%02X value=%.2f bytes=%s",
                     param_id, value, frame.hex())
        except Exception as e:
            log.error("Write failed: %s", e)


def on_mqtt_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace").strip()
    log.info("MQTT command: %s = %r", topic, payload)
    try:
        if topic.endswith("/cmd/dhw_setpoint"):
            v = float(payload)
            if 25.0 <= v <= 75.0:
                send_write(WRITE_PARAMS["dhw_setpoint"][0], v)
            else:
                log.warning("DHW setpoint %s out of allowed range 25-75", v)
        elif topic.endswith("/cmd/heating_curve"):
            v = float(payload)
            if -3.0 <= v <= 3.0:
                send_write(WRITE_PARAMS["heating_curve"][0], v)
            else:
                log.warning("Heating curve %s out of allowed range -3..+3", v)
        elif topic.endswith("/cmd/mode"):
            # Map friendly name → numeric value
            # Confirmed via cloud API setdata par4: 0=Standby, 1=Heating, 2=Cooling, 3=DHW Only, 4=Auto
            name_to_value = {
                "Standby":  0,
                "Heating":  1,
                "Cooling":  2,
                "DHW Only": 3,
                "Auto":     4,
            }
            v = name_to_value.get(payload)
            if v is None:
                log.warning("Unknown mode '%s'", payload)
                return
            send_write(WRITE_PARAMS["mode"][0], v)
        elif topic.endswith("/cmd/power"):
            v = 1.0 if payload.upper() in ("ON", "1", "TRUE") else 0.0
            send_write(WRITE_PARAMS["power"][0], v)
        else:
            # Try matching against extended writes (auto-routed by key)
            suffix = topic.rsplit("/", 1)[-1]   # e.g. "vacation_mode"
            matched = None
            for ew in EXTENDED_WRITES:
                if ew["key"] == suffix:
                    matched = ew
                    break
            if matched is None:
                log.warning("Unknown command topic: %s", topic)
                return
            if matched["type"] == "switch":
                v = 1.0 if payload.upper() in ("ON", "1", "TRUE") else 0.0
            else:  # number
                v = float(payload)
                if not (matched["min"] <= v <= matched["max"]):
                    log.warning("Value %s out of allowed range %s..%s for %s",
                                v, matched["min"], matched["max"], suffix)
                    return
            send_write(matched["local_byte"], v)
    except (ValueError, KeyError) as e:
        log.error("Command parse error: %s", e)


def stream_frames(sock: socket.socket):
    buf = bytearray()
    # Set a short read timeout so we can loop and detect TRUE connection failures
    # via TCP keepalive, while tolerating quiet periods (heat pump in standby)
    sock.settimeout(5.0)
    last_data = time.time()
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            # Quiet period (e.g. heat pump in standby) is normal — don't drop connection
            silent_for = time.time() - last_data
            if silent_for > 300:  # 5 min of total silence → assume something is really wrong
                raise ConnectionError(f"No data for {silent_for:.0f}s — reconnecting")
            log.debug("No data for %.0fs (quiet ok)", silent_for)
            continue
        if not chunk:
            raise ConnectionError("W600 closed connection")
        last_data = time.time()
        buf.extend(chunk)
        while True:
            s_idx = buf.find(STATUS_HDR)
            c_idx = buf.find(CONFIG_HDR)
            cands = [(s_idx, "status", FRAME_LEN), (c_idx, "config", CONFIG_LEN)]
            cands = [c for c in cands if c[0] >= HDR_OFFSET]
            if not cands:
                if len(buf) > 16384:
                    buf = buf[-1024:]
                break
            idx, ftype, flen = min(cands)
            fs = idx - HDR_OFFSET
            if len(buf) < fs + flen:
                break
            yield ftype, bytes(buf[fs:fs+flen])
            del buf[:fs+flen]


def parse_args():
    p = argparse.ArgumentParser(description="Gorenje Aerogor → Home Assistant bridge")
    p.add_argument("-v", "--verbose", action="count", default=0,
                   help="-v: show INFO (connections, writes). -vv: DEBUG (every published frame).")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="Only log errors. Recommended for systemd long-running.")
    p.add_argument("--w600", default=W600_HOST, help="W600 IP (env: W600_HOST)")
    p.add_argument("--mqtt", default=MQTT_HOST, help="MQTT broker IP (env: MQTT_HOST)")
    p.add_argument("--user", default=MQTT_USER, help="MQTT username (env: MQTT_USER)")
    p.add_argument("--password", default=MQTT_PASS, help="MQTT password (env: MQTT_PASS)")
    return p.parse_args()


def main():
    args = parse_args()
    if args.quiet:        level = logging.ERROR
    elif args.verbose >= 2: level = logging.DEBUG
    elif args.verbose >= 1: level = logging.INFO
    else:                  level = logging.WARNING   # default: quiet, only warns/errors
    logging.basicConfig(level=level,
                        format="%(asctime)s %(levelname)s %(message)s")

    global W600_HOST, MQTT_HOST, MQTT_USER, MQTT_PASS
    W600_HOST = args.w600
    MQTT_HOST = args.mqtt
    MQTT_USER = args.user
    MQTT_PASS = args.password

    client = mqtt.Client(client_id=f"{DEVICE_ID}_bridge")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.will_set(f"{DEVICE_ID}/availability", "offline", retain=True)
    client.on_message = on_mqtt_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    publish_discovery(client)
    client.subscribe(f"{DEVICE_ID}/cmd/+")
    client.publish(f"{DEVICE_ID}/availability", "online", retain=True)

    # Load persisted state from disk (preserves setpoints/mode across restarts)
    state: dict = {}
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE) as f:
            state = json.load(f)
        log.info("Loaded %d cached state values from %s", len(state), STATE_FILE)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        log.info("No cached state (%s) — starting fresh", e)

    # Immediately publish loaded state so HA gets values before any frame arrives
    if state:
        client.publish(f"{DEVICE_ID}/state", json.dumps(state), retain=True)

    # Start watchdog thread — kills the process if no publish in WATCHDOG_TIMEOUT_S
    global _last_publish_ts
    _last_publish_ts = time.time()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    log.info("Watchdog started (timeout=%d s)", WATCHDOG_TIMEOUT_S)

    last_pub = 0.0
    last_save = 0.0
    while True:
        try:
            sock = open_w600()
            for ftype, frame in stream_frames(sock):
                if ftype == "status":
                    state.update(parse_frame(frame, FIELDS))
                else:
                    state.update(parse_frame(frame, CONFIG_FIELDS))
                now = time.time()
                if now - last_pub >= 1 / PUBLISH_HZ:
                    # retain=True so HA gets last-known values on reconnect
                    client.publish(f"{DEVICE_ID}/state", json.dumps(state),
                                   retain=True)
                    log.debug("Published state: %s", state)
                    last_pub = now
                    _last_publish_ts = now  # pet the watchdog
                if now - last_save >= SAVE_EVERY_S:
                    try:
                        tmp = STATE_FILE + ".tmp"
                        with open(tmp, "w") as f:
                            json.dump(state, f)
                        os.replace(tmp, STATE_FILE)
                        last_save = now
                    except OSError as e:
                        log.warning("Could not save state to %s: %s", STATE_FILE, e)
        except (socket.timeout, ConnectionError, OSError) as e:
            log.warning("Connection lost (%s) — retry in 10 s", e)
            client.publish(f"{DEVICE_ID}/availability", "offline", retain=True)
            time.sleep(10)


def watchdog_loop() -> None:
    """Monitor _last_publish_ts; if stale beyond WATCHDOG_TIMEOUT_S, kill
    the process so systemd restarts it.

    This catches silent hangs where the main thread is stuck in a syscall
    (e.g. socket.recv blocked indefinitely after a network glitch) and
    systemd would otherwise not detect a problem because the process is
    still 'running'."""
    while True:
        time.sleep(60)  # check every minute
        if _last_publish_ts == 0:
            continue   # not yet started
        age = time.time() - _last_publish_ts
        if age > WATCHDOG_TIMEOUT_S:
            log.error(
                "WATCHDOG: no publish in %.0f s (> %d s). Killing process so "
                "systemd will restart it.", age, WATCHDOG_TIMEOUT_S,
            )
            # Force-exit. Skip cleanup intentionally — we want systemd to
            # start fresh, not have a Python finally-block hang us too.
            os._exit(75)  # 75 = EX_TEMPFAIL conventional exit code


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        log.info("Exit"); sys.exit(0)
