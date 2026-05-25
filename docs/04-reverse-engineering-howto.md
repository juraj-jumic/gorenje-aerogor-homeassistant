# Part 4 — Discovering new parameters

If your OEM variant of the Heatstar controller (or your firmware build) has different parameter IDs than what we documented in Part 3, you can repeat the discovery process. This guide walks through it.

## Prerequisites

- The bridge from Part 2 already deployed and working for reads.
- The MITM proxy script (`scripts/mitm_proxy.py`) on the same machine.
- The MyHeatPump app installed on your phone, working normally.

## Approach overview

We sit a transparent proxy between the W600 and the cloud. When you change a setting in the app, the cloud sends a write command to the controller — we capture that command, decode its parameter ID and value, and add it to the bridge.

```
W600 ──SocketB──►  proxy on your LAN ──► myheatpump.com
                       │
                       │ logs bytes both directions
                       ▼
                  capture files
```

## Step 1 — Set up the proxy as a systemd service (transparent mode, no logging)

Create `/etc/systemd/system/mitm_proxy.service`:

```ini
[Unit]
Description=W600 ↔ MyHeatPump cloud transparent proxy
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/aerogor/mitm_proxy.py
WorkingDirectory=/opt/aerogor
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable --now mitm_proxy
```

By default the proxy is silent — no logs, no capture files. It just relays bytes. Safe to leave running 24/7.

## Step 2 — Repoint the W600 to your proxy

In the W600's web UI:

- Trans Setting → **SocketB Connect Setting**
- Change **Server IP Address** from `www.myheatpump.com` to your proxy's LAN IP (e.g. `192.168.0.10`)
- Keep **Port = 18899**, **Protocol = TCP-Client**
- Save
- System Setting → Restart Module

Within ~30 seconds the W600 reconnects, this time through your proxy. The MyHeatPump app keeps working transparently.

## Step 3 — Capture a specific action

When you want to learn a new parameter:

```bash
systemctl stop mitm_proxy
python3 /opt/aerogor/mitm_proxy.py -c -v
```

`-c` enables file capture. `-v` shows connection events on stdout.

Wait for `W600 connected from ...` and `Upstream connected to ...`. Then in the MyHeatPump app, **do exactly one thing** (e.g. change DHW setpoint from 40 to 41). Wait 5-10 seconds. Do it back (41 → 40).

Wait ~60 more seconds so a config frame fires after each change (this lets us confirm what value changed in response).

`Ctrl+C` to stop. Two files appear in the working directory:

- `from_w600_<timestamp>.bin` — controller → cloud (status + config)
- `to_w600_<timestamp>.bin` — cloud → controller (writes, **the prize**)

Restart the silent proxy:

```bash
systemctl start mitm_proxy
```

## Step 4 — Decode the capture

```python
import struct

MAGIC = b'\x55\xAA\x01\xD8\xB0\x4C\xF7\xB3\x5A\x01'

data = open('to_w600_...bin', 'rb').read()
positions = []
i = 0
while True:
    idx = data.find(MAGIC, i)
    if idx < 0: break
    positions.append(idx)
    i = idx + len(MAGIC)

for j, pos in enumerate(positions):
    end = positions[j+1] if j+1 < len(positions) else len(data)
    msg = data[pos:end]
    if len(msg) >= 22 and msg[10] == 0x07:
        param = msg[13]
        val = struct.unpack('<f', msg[15:19])[0]
        print(f"param 0x{param:02X}  value={val}")
```

You should see one or two writes corresponding to your test changes. Note the parameter ID and the values sent.

## Step 5 — Verify in the config frame

To confirm the parameter ID truly means what you think, look at the `from_w600` capture and find where the value changes:

```python
from_data = open('from_w600_...bin', 'rb').read()
CONFIG_HDR = b'\x23\x02\x02\x00'

positions = []
i = 0
while True:
    idx = from_data.find(CONFIG_HDR, i)
    if idx < 0: break
    positions.append(idx - 10)
    i = idx + 1

# Compare successive config frames byte by byte
import struct
prev = None
for j, pos in enumerate(positions):
    f = from_data[pos:pos+562]
    if prev is not None:
        for off in range(35, 558, 4):
            v_prev = struct.unpack_from('<f', prev, off)[0]
            v_new  = struct.unpack_from('<f', f, off)[0]
            if abs(v_prev - v_new) > 0.001 and abs(v_prev) < 1000 and abs(v_new) < 1000:
                print(f"Config {j-1}→{j}: offset {off} changed {v_prev:.2f} → {v_new:.2f}")
    prev = f
```

This shows you which config-frame offset stores the parameter. Add it to the bridge's `CONFIG_FIELDS` map so HA can read it back as a sensor.

## Step 6 — Add the new parameter to the bridge

In `aerogor_bridge.py`, two places to edit:

1. **`WRITE_PARAMS`** (top of file) — add a row with your parameter ID and constraints
2. **`CONFIG_FIELDS`** — add the offset you discovered in Step 5
3. **`publish_discovery()`** — add a discovery message for the new HA entity (number, switch, select, etc.)
4. **`on_mqtt_message()`** — add a handler for the new command topic

Restart the bridge (`systemctl restart aerogor`) and the new control appears in HA automatically.

## Tips for tricky parameters

**Heating curve was tricky in the original capture because it's a -3..+3 slider** but it appears as a normal float in the protocol — make sure your range constraints in `WRITE_PARAMS` allow negatives.

**Mode/state values appear as bytes, not floats, in the config frame** (offset 30 is a single byte). For these, parse with `frame[offset]` instead of `struct.unpack_from('<f', ...)`. The write command still sends a float-encoded integer (e.g. 4.0 for Auto).

**Some settings the app shows aren't actually persisted by the controller** — they're computed display values. If a parameter doesn't appear in any config frame even after you change it, that's the cause. The change might still be effective; it just isn't represented as a parameter.

## Safety reminders

- Never send commands to parameter IDs you haven't observed in cloud traffic. The MyHeatPump app shapes what the cloud writes; the controller has hundreds more parameters that aren't user-facing, and writing arbitrary values to them can cause real problems.
- Always test a new write with values within the normal range the app shows.
- Keep a panel-side baseline backup of important settings (legionella schedule, weather curve, etc.) before experimenting.
- Run the bridge in `-v` mode initially when you add a new control so you can see exactly what bytes go out.

## Reverting the MITM setup

When you're done with discovery and want the MyHeatPump app back on the official cloud path:

- W600 web UI → Trans Setting → SocketB Server IP Address → back to `www.myheatpump.com`
- Save → Restart Module
- The proxy can remain running (it's silent and harmless) or you can disable it: `systemctl disable --now mitm_proxy`

Captures stay on disk until you remove them. A cron line cleans up after a week:

```bash
# /etc/cron.daily/clean-mitm-captures
find /opt/aerogor -name "from_w600_*.bin" -mtime +7 -delete
find /opt/aerogor -name "to_w600_*.bin" -mtime +7 -delete
```

## Panel sleep mitigation (if applicable)

If your panel goes into a deep sleep state that breaks app/HA control (only physically touching the screen wakes it up), this is a Windows CE OS-level setting, not in the heat pump app. Enter installer/service mode on the panel, open Control Panel → Power Properties, and set every timeout (System Idle, Suspend, User Idle) to **Never**. Reboot the panel to confirm.
