# Gorenje Aerogor → Home Assistant

End-to-end guide and tooling for integrating a Gorenje Aerogor 6AS air-to-water heat pump (or any rebadge of the same Heatstar / AMITIME OEM controller) into Home Assistant, with **full local read and write control** over the proprietary serial-over-Wi-Fi protocol.

Works for any heat pump that:
- Has a Heatstar controller (6" Windows CE touch panel) built by AMITIME
- Uses a USR-W600 module for Wi-Fi connectivity
- Is controlled by the "MyHeatPump" cloud app

Known rebadges include Gorenje Aerogor, Neoheat, and several other European brands using the same OEM platform.

> ⚠️ This integration writes directly to a heat pump's controller over a reverse-engineered protocol. Wrong values for some parameters could cause unsafe operation (corrupted legionella schedules, wrong setpoints, etc). The parameters exposed here have been verified against an actual unit, but you assume all risk if you deploy this.

## What you get

22 live sensors and 4 controls in Home Assistant, all fully local:

**Sensors** (1 Hz updates): water outlet/return/coil temps, DHW tank, room temp, compressor frequency, EEV opening, high/low pressures, ambient/outdoor/suction/discharge temps, fan speed, compressor current, line voltage, active setpoint, software version, DHW setpoint, heating water setpoint, heating curve.

**Controls**: DHW setpoint slider (25-75 °C), heating curve parallel move (-3 to +3 °C), operating mode select (Auto/Standby + others), power switch.

## How it works (architecture)

```
┌──────────────┐    serial      ┌──────────┐  Wi-Fi   ┌─────────────┐
│  Heat pump   │ ◄────RS-485──► │  Heat-   │ ◄──RS-232► USR-W600   │
│  controller  │                │  star    │           │  module     │
│  (Modbus     │                │  panel   │           │             │
│   internal)  │                │  (WinCE) │           │             │
└──────────────┘                └──────────┘           └──────┬──────┘
                                                              │ Wi-Fi
                                                              ▼
                                                       ┌─────────────┐
                                                       │ Home LAN    │
                                                       │             │
                                                       │  ┌────────┐ │
                                                       │  │ Bridge │ │  ← Python
                                                       │  │ (this  │ │     script,
                                                       │  │  repo) │ │     runs as
                                                       │  └────┬───┘ │     systemd
                                                       │       │ MQTT│     service
                                                       │  ┌────▼───┐ │     on Proxmox
                                                       │  │ Home   │ │     or LXC
                                                       │  │ Assist │ │
                                                       │  └────────┘ │
                                                       └─────────────┘
```

The W600 module is configured to expose its serial traffic on TCP port 8899 (SocketA). The Python bridge connects there, parses the proprietary binary frames into sensor values, publishes them to MQTT with Home Assistant discovery, and accepts write commands back from MQTT.

The MyHeatPump cloud app keeps working — it uses the W600's outbound SocketB connection, which is independent of SocketA. No need to disable the cloud to use HA control.

## Repository contents

```
.
├── README.md                — you are here
├── scripts/
│   ├── aerogor_bridge.py    — the main HA bridge (read + write)
│   └── mitm_proxy.py        — MITM proxy used to reverse-engineer cloud writes
├── systemd/
│   ├── aerogor.service      — systemd unit for the bridge
│   └── mitm_proxy.service   — systemd unit for the proxy (optional)
├── docs/
│   ├── 01-haos-on-laptop.md            — install HA OS on a spare laptop via Proxmox
│   ├── 02-deploy-bridge.md             — install the bridge as a systemd service
│   ├── 03-protocol-reference.md        — the binary protocol, decoded
│   └── 04-reverse-engineering-howto.md — how to discover new parameter IDs
└── reference/
    ├── heatstar_params.md    — translated parameter dictionary (500 settings)
    └── heatstar_params.csv   — same, as CSV
```

## Quick start

If you already have Home Assistant + an MQTT broker:

```bash
# On any always-on Linux box on the same LAN as your W600
apt install python3-pip
pip install paho-mqtt --break-system-packages
wget https://gitlab.com/<your-user>/<this-repo>/raw/main/scripts/aerogor_bridge.py
nano aerogor_bridge.py   # edit W600_HOST, MQTT_HOST, MQTT_PASS
python3 aerogor_bridge.py -v
```

Within seconds you should see a "Gorenje Aerogor" device appear in HA → Settings → Devices & Services → MQTT, with all sensors populating.

For a full from-scratch setup (spare laptop → Proxmox → HA → bridge), follow [docs/01-haos-on-laptop.md](docs/01-haos-on-laptop.md).

## How this was built

This integration didn't exist before — the protocol is proprietary, the OEM doesn't publish docs, and the Itho Daalderop Amber community integration (which uses the same Heatstar controller family) doesn't apply because each OEM ships a customized firmware with different parameter mappings.

The full reverse-engineering process is documented in [docs/04-reverse-engineering-howto.md](docs/04-reverse-engineering-howto.md). The short version:

1. Captured the W600's outbound TCP stream from a regular LAN connection — revealed two frame types (status, 198 bytes, 1 Hz; config, 562 bytes, ~1/min) with little-endian IEEE-754 floats.
2. Extracted `HeatStar.db` (SQLite) from the Windows CE panel via a network share — gave 500 parameter definitions including names, ranges, and live sensor field schemas.
3. Set up an MITM proxy by repointing the W600's SocketB cloud destination to a local machine, transparently forwarding to `myheatpump.com` while logging both directions.
4. Triggered known actions in the MyHeatPump app (DHW setpoint changes, mode changes, power toggles) and decoded the captured cloud→W600 write commands.
5. Cracked the CRC algorithm: **CRC-16/Modbus over bytes [2:-3], stored little-endian**.
6. Built and verified an encoder that reproduces all captured commands byte-perfectly.

The whole project took about three evenings of work.

## Acknowledgements

- The [Itho Daalderop Amber HA integration](https://github.com/remmob/itho_amber) by remmob — confirmed the Heatstar OEM lineage and gave hints about the Modbus internals (not directly usable here due to firmware differences, but valuable as a reference).
- The Home Assistant MQTT discovery spec, which makes external integrations trivial.

## License

MIT. Use at your own risk. If you adapt this for another OEM variant, please contribute the parameter ID differences back.
