# Part 2 — Deploy the Aerogor bridge

The bridge is a small Python program that reads sensor data from the W600 and publishes it to MQTT, where Home Assistant picks it up.

This guide assumes you've completed [Part 1](01-haos-on-laptop.md) and have Proxmox + Home Assistant running.

## Prerequisites — on the W600 side

You need to know the W600's IP on your LAN. Either:

- Find it in your router's "Connected Clients" page (look for a device named `USR-W600` or with a MAC starting with `D8:B0:4C`), or
- Look at the W600's web UI → System Status page (you'll need to know its IP to get there, so this only works once you've found it).

**Reserve this IP in your router's DHCP table** — without that, the bridge will break when the IP changes.

Also confirm the W600 is in **STA mode** (joined to your Wi-Fi) and on the **same subnet as the rest of your devices**. If it's on a guest network or a separate router with a different IP range, MITM and some integrations get complicated. Connect it to the main network.

## Step 1 — Set up Mosquitto in Home Assistant

The bridge talks to HA via MQTT. HA's Mosquitto add-on is the broker.

In Home Assistant:

1. Settings → **Apps → Add-on Store** → search "Mosquitto broker" → Install
2. After install, on its detail page: Info tab → toggle **Start on boot** and **Watchdog** on
3. Click **Start**
4. Check the Log tab for "starting" lines and no errors

## Step 2 — Create the MQTT user

Settings → **People** → Add Person:

- Display Name: `mqtt`
- Username: `mqtt`
- "Allow person to login": **on**, set a strong password
- Administrator: **off**

Remember the password — the bridge needs it.

## Step 3 — Add the MQTT integration to HA

Settings → **Devices & Services** → **+ Add Integration** → search "MQTT" → click it.

The dialog should pre-fill:
- Broker: `core-mosquitto`
- Port: `1883`

Add username `mqtt` and the password from Step 2. Submit.

## Step 4 — Install the bridge on Proxmox

We'll run it directly on the Proxmox host as a systemd service. Alternative: create a small LXC container — same steps inside the container.

In Proxmox web UI → click your node → **Shell**:

```bash
apt update && apt install -y python3-pip
pip install paho-mqtt --break-system-packages
mkdir -p /opt/aerogor
cd /opt/aerogor
wget -O aerogor_bridge.py https://gitlab.com/<your-user>/<this-repo>/raw/main/scripts/aerogor_bridge.py
```

(Replace the URL with wherever you've published this repo, or copy the file via SCP.)

## Step 5 — Configure the bridge

The bridge reads config from environment variables, not from the file itself — so you never need to edit the Python code.

Create the systemd unit:

```bash
nano /etc/systemd/system/aerogor.service
```

Paste:

```ini
[Unit]
Description=Aerogor heat pump → Home Assistant MQTT bridge
After=network-online.target
Wants=network-online.target

[Service]
Environment="W600_HOST=192.168.0.50"
Environment="MQTT_HOST=192.168.0.20"
Environment="MQTT_USER=mqtt"
Environment="MQTT_PASS=your-mqtt-password-here"
ExecStart=/usr/bin/python3 /opt/aerogor/aerogor_bridge.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Fill in the right values:
- `W600_HOST` — the W600's reserved IP
- `MQTT_HOST` — the **HAOS VM's** IP (this is the Mosquitto broker's address)
- `MQTT_PASS` — what you set in Step 2

Save and exit.

## Step 6 — Enable and start

```bash
systemctl daemon-reload
systemctl enable --now aerogor
systemctl status aerogor
```

You should see "active (running)" in green. If it's red, check:

```bash
journalctl -u aerogor -n 30
```

Common errors:
- `Connection refused`: MQTT broker isn't running or IP is wrong
- `Authentication failed`: MQTT password mismatch
- `No route to host`: W600 IP wrong or unreachable

## Step 7 — Verify in HA

In Home Assistant → Settings → Devices & Services → **MQTT** → click into it → **Devices**. You should see:

- A device named **"Gorenje Aerogor"**
- ~22 sensor entities populating with live values
- 4 control entities: DHW Setpoint (number), Heating Curve Move (number), Operating Mode (select), Heat Pump Power (switch)

If the sensors say "Unknown" for more than 2 minutes after starting, see the troubleshooting section below.

## Step 8 — Build a dashboard

HA → Overview → top-right pencil → Edit Dashboard. Useful first cards for an Aerogor:

- **Tile** showing DHW Tank temperature
- **Gauge** of Compressor Frequency (0-100 Hz)
- **History graph** with Water Outlet + Water Return + Ambient over 24 hours
- **Entities** card grouping the controls (DHW Setpoint, Heating Curve, Operating Mode, Power)

## Step 9 — Apple Home (optional)

To expose Aerogor controls to Siri and the Apple Home app:

Settings → Devices & Services → **+ Add Integration** → search "HomeKit Bridge". Pick:
- Name: `HASS Bridge`
- Mode: **Bridge**
- Domain filter: tick `switch`, `select`, `number`, `climate`

Submit, then in Apple Home app: + → Add Accessory → scan the QR code shown on the HomeKit Bridge integration page.

Now Siri controls everything: "Hey Siri, set DHW to 45 degrees."

## Troubleshooting

**Bridge logs "Connection lost" repeatedly:** the W600 might be dropping idle connections. The bridge handles short gaps gracefully but if you see this every few seconds, restart the W600 (web UI → System Setting → Restart Module) to clear any zombie connections.

**Sensors show "Unknown" forever (especially DHW Setpoint, Heating Setpoint, Heating Curve):** these come from "config frames" which the controller only emits about once per minute. Be patient. If it's still unknown after 5 min, run the bridge manually with `-v` and see if config frames are arriving.

**HA shows the heat pump as "Unavailable":** the bridge's TCP connection to the W600 dropped. Check `journalctl -u aerogor -n 50` for the cause. If it's "no data for 300s" repeatedly, the controller has gone fully silent (maybe panel sleep — see Part 4 troubleshooting).

**Bridge can't connect to W600:** verify W600 IP with `nc -zv <w600-ip> 8899`. If "connection refused", the W600 might be in AP mode rather than STA. If "no route to host", the IP is wrong or the W600 dropped off Wi-Fi.

**Bridge runs but no device appears in HA:** Mosquitto credentials likely wrong. Check Mosquitto's log in HA (Settings → Apps → Mosquitto → Log) for failed authentication attempts.
