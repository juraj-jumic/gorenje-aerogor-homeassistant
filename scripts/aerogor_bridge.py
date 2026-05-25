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
# 0x3F = Auto (before the user set Auto), 0x40 = changed value after writing mode=4
# We'll track the raw byte and map it to a friendly label
MODE_OFFSET = 30
MODE_MAP = {
    # Confirmed by user-reported state transitions in capture:
    0x3F: "Standby",    # initial state (user reported "Standby")
    0x40: "Auto",       # after sending mode=4 (user reported "Auto")
    # Other byte values (other modes) still unknown — need more captures
}

# Writable parameters (confirmed by reverse-engineering cloud writes)
WRITE_PARAMS = {
    "dhw_setpoint":     (0x36, "float", 25.0, 75.0, "DHW Setpoint",        "°C"),
    "power":            (0x00, "bool",  0,    1,    "System Power",        None),
    "heating_curve":    (0x78, "int",  -3,    3,    "Heating Curve Move",  "°C"),
    "mode":             (0x03, "int",   1,    5,    "Operating Mode",      None),
}

# Mode values confirmed/inferred:
#   4 = Auto (confirmed by capture)
# Others (1, 2, 3, 5) likely: heating-only, cooling-only, DHW-only, standby
# Need more captures to map exact values. For now, allow integer range 1-5
# and the user can experiment safely from the panel as fallback.

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
            "options": ["Heating", "Cooling", "DHW Only", "Auto", "Standby"],
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


# Shared TCP socket — both reader and writer share it
_sock_lock = threading.Lock()
_sock: socket.socket | None = None


def open_w600() -> socket.socket:
    global _sock
    s = socket.create_connection((W600_HOST, W600_PORT), timeout=10)
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
            name_to_value = {
                "Heating":  1, "Cooling": 2, "DHW Only": 3,
                "Auto":     4, "Standby": 5,
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
            log.warning("Unknown command topic: %s", topic)
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

    last_pub = 0.0
    state: dict = {}
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
                    client.publish(f"{DEVICE_ID}/state", json.dumps(state),
                                   retain=False)
                    log.debug("Published state: %s", state)
                    last_pub = now
        except (socket.timeout, ConnectionError, OSError) as e:
            log.warning("Connection lost (%s) — retry in 10 s", e)
            client.publish(f"{DEVICE_ID}/availability", "offline", retain=True)
            time.sleep(10)


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        log.info("Exit"); sys.exit(0)
