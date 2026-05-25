# Part 3 — Aerogor binary protocol reference

This document describes the proprietary protocol the Heatstar controller speaks over its serial port (which the USR-W600 module bridges to TCP).

All values reverse-engineered from packet captures against a Gorenje Aerogor 7AS with firmware build `SIZE7 V2.03_1 for GORENJE002`. Other OEM rebadges (Neoheat, etc.) using the same Heatstar engine should be similar but may have parameter ID differences — confirm before writing.

## Transport

- **Hardware path**: Heatstar panel COM2 (RS-232, 115200 baud, 8N1, no flow control) ↔ USR-W600 module ↔ Wi-Fi
- **Network path**: TCP server on W600 port 8899 (SocketA, LAN-side) and TCP client to `www.myheatpump.com:18899` (SocketB, cloud-side). Both carry the same byte stream transparently.

## Frame types

The controller emits two frame types. Both share an identical 10-byte prefix:

```
55 AA 01 D8 B0 4C F7 B3 5A 01
^^^^^                          magic
      ^^                       version?
         ^^ ^^ ^^              device ID
                  ^^           ?
                     ^^        ?
```

Frame type is determined by bytes 10-13:

| Bytes [10:14]   | Total length | Direction       | Purpose                                      | Frequency |
| --------------- | ------------ | --------------- | -------------------------------------------- | --------- |
| `B7 00 01 00`   | 198 bytes    | controller → cloud / LAN | live sensor readings ("status frame") | ~1 Hz     |
| `23 02 02 00`   | 562 bytes    | controller → cloud / LAN | persistent settings ("config frame")  | ~1/min    |
| `07 00 05 ??`   | 22 bytes     | cloud → controller       | parameter write                       | on demand |

Heartbeat pings (16 bytes, type `01 00 03 62 05 3A`) appear periodically in the cloud→W600 direction. Safe to ignore.

## Status frame format (B7 00 01 00, 198 bytes)

Floats are little-endian IEEE-754, aligned to offset 35 mod 4 from frame start. Values are confirmed against panel display screenshots.

| Offset | Type   | Field name           | Description                       | Sanity range |
| ------ | ------ | -------------------- | --------------------------------- | ------------ |
| 35     | float  | water_outlet         | Water outlet temp (Tuo)           | -50..150 °C  |
| 39     | float  | water_return         | Water return temp (Tui)           | -50..150 °C  |
| 43     | float  | indoor_coil          | Indoor coil temp (Tup)            | -50..150 °C  |
| 47     | float  | dhw_tank             | DHW tank temp (TW)                | -50..150 °C  |
| 51     | float  | heating_water        | Heating/cooling water temp (TC)   | -50..150 °C  |
| 59     | float  | room_temp            | Room temperature                  | -50..150 °C  |
| 63     | float  | valve2_temp          | Valve 2 temp (Tv2)                | -50..150 °C  |
| 99     | float  | compressor_hz        | Compressor inverter frequency     | 0..200 Hz    |
| 103    | float  | eev_opening          | Electronic expansion valve (P)    | 0..500       |
| 107    | float  | high_pressure        | High-side pressure (Pd)           | 0..60 bar    |
| 111    | float  | low_pressure         | Low-side pressure (Ps)            | 0..60 bar    |
| 115    | float  | ambient_temp         | Outdoor ambient                   | -50..70 °C   |
| 119    | float  | line_status          | Line/circuit status               | 0..100 %     |
| 123    | float  | suction_temp         | Compressor suction (Ts)           | -50..150 °C  |
| 127    | float  | outdoor_coil         | Outdoor coil (Tp)                 | -50..150 °C  |
| 131    | float  | fan_speed            | Outdoor fan RPM                   | 0..5000      |
| 139    | float  | compressor_amps      | Compressor current                | 0..100 A     |
| 143    | float  | line_voltage         | Mains voltage                     | 100..300 V   |
| 163    | float  | active_setpoint      | Current active setpoint           | -50..150 °C  |
| 167    | float  | sw_version           | Software version number           | (e.g. 203)   |

Other offsets contain values that are zero in idle states or haven't been mapped yet (discharge temp, fan speed 2, etc).

## Config frame format (23 02 02 00, 562 bytes)

Same float convention.

| Offset | Type  | Field name        | Description                |
| ------ | ----- | ----------------- | -------------------------- |
| 30     | byte  | mode_raw          | Operating mode (see below) |
| 231    | float | dhw_setpoint      | DHW setpoint               |
| 247    | float | heating_setpoint  | Heating water setpoint     |
| 495    | float | heating_curve     | Curve parallel move (-3..+3) |

Many other parameters live in this frame too. The full 500-entry parameter dictionary is in [reference/heatstar_params.md](../reference/heatstar_params.md), extracted from the panel's SQLite database.

### Mode byte values (offset 30)

| Byte | Meaning  |
| ---- | -------- |
| 0x3F | Standby  |
| 0x40 | Auto     |

Other values (Heating only, Cooling only, DHW only) are not yet mapped — they require additional captures with the panel in those modes.

## Write command format (07 00 05 XX, 22 bytes)

Sent cloud → controller (or, in our case, bridge → controller). Structure:

```
 0  1   2  3  4  5  6  7  8  9  | 10 11 12 | 13 | 14 | 15 16 17 18 | 19 20 | 21
55 AA  01 D8 B0 4C F7 B3 5A 01    07 00 05   PP   00   VV VV VV VV   CC CC   3A
\_________MAGIC___________/      \__TYPE_/  PID  PAD  \_LE_FLOAT__/  CRC    END
```

Where:
- `PP` = parameter ID (see table below)
- `VV VV VV VV` = 4-byte little-endian IEEE-754 float value
- `CC CC` = CRC-16/Modbus, little-endian, computed over bytes [2:19] (everything after the 55 AA magic, up to and excluding the CRC itself)
- `3A` = `:` terminator (constant)

### Confirmed writable parameter IDs

| Param | Description       | Value semantics                 | Confirmed |
| ----- | ----------------- | ------------------------------- | --------- |
| 0x00  | System power      | 0.0 = OFF, 1.0 = ON             | ✓         |
| 0x03  | Operating mode    | 4.0 = Auto. Others not mapped.  | partial   |
| 0x36  | DHW setpoint      | absolute °C as float (25..75)   | ✓         |
| 0x78  | Heating curve move| signed °C as float (-3..+3)     | ✓         |

These are what the official MyHeatPump cloud app sends. Don't write to arbitrary parameter IDs — they may have side effects in unknown areas of controller state.

### CRC implementation

Standard CRC-16/Modbus:

```python
def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF
```

Apply to bytes [2:19] (i.e. `data[2:-3]`). Result is appended **little-endian**.

### Example commands

DHW setpoint to 33.0 °C:
```
55 AA 01 D8 B0 4C F7 B3 5A 01 07 00 05 36 00 00 00 04 42 0E 85 3A
```

System power ON:
```
55 AA 01 D8 B0 4C F7 B3 5A 01 07 00 05 00 00 00 00 80 3F A8 32 3A
```

Heating curve to +3 °C:
```
55 AA 01 D8 B0 4C F7 B3 5A 01 07 00 05 78 00 00 00 40 40 B3 AA 3A
```

## Notes on bidirectional use

The W600 in transparent mode forwards data both ways between TCP and serial. A client connected to SocketA (TCP port 8899) can:

1. Read frames sent by the controller (status, config) by parsing inbound bytes.
2. Send write commands to the controller by writing the 22-byte frames as raw bytes.

The cloud (via SocketB) does the same, so locally-issued writes coexist with cloud-issued writes — both go to the same serial port. No special framing or addressing is needed because the controller acts on whatever frame it receives next.

## Internal Modbus bus (separate from this protocol)

The Heatstar panel internally uses **Modbus RTU on RS-485** (COM1, 19200 baud 8E1, slave address 110) to talk to the heat pump's main control board. The W600 is NOT connected to this bus — it's on COM2 (RS-232) where the cloud telemetry protocol described above runs.

If you wanted full register-level control (every internal value, not just what the cloud app exposes), tapping that RS-485 bus is a cleaner long-term solution than this protocol. But for typical end-user needs — reading sensors, changing setpoints, choosing modes — the protocol described here is sufficient.
