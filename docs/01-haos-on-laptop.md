# Part 1 — Home Assistant on a spare laptop (via Proxmox)

This guide turns any unused laptop with at least 4 GB RAM into a permanent Home Assistant server, with room left over to run additional services (the Aerogor bridge, file sharing, etc).

We install **Proxmox VE** as the host operating system, then run Home Assistant OS as a VM inside it. This gives full HA features (Add-ons, Supervisor) plus the flexibility to add more services later as VMs or LXC containers.

## What you'll need

- A spare laptop or mini PC: x86-64 CPU, ≥4 GB RAM, ≥64 GB storage, Ethernet port (Wi-Fi is doable but flaky for a server).
- A USB stick (≥4 GB) for the Proxmox installer.
- A second computer to run the Proxmox web UI from (any modern browser).
- Ethernet cable from the laptop to your router for setup. Long-term it can stay wired or go Wi-Fi.

## Step 1 — Prep the laptop's BIOS

Boot into BIOS (usually F2, Del, or F10 at power-on). Set:

- **Virtualization (Intel VT-x / AMD-V or SVM)**: enabled
- **Secure Boot**: disabled
- **USB boot**: enabled, USB as first boot device
- **Sleep on lid close**: disabled if there's a BIOS option (we'll also do this in the OS)

Note: anything on the laptop's hard drive will be wiped. Back up first.

## Step 2 — Flash Proxmox VE installer

1. Download Proxmox VE ISO (current LTS) from https://proxmox.com/en/downloads
2. Flash to USB with Balena Etcher (https://etcher.io). On Windows, Etcher may complain that the resulting USB looks "corrupted" — ignore the warning, it's fine.
3. Plug USB into laptop, boot from it (boot menu key varies: F12, Esc, F10).

## Step 3 — Install Proxmox

Choose "Install Proxmox VE (Graphical)". Walk through:

- **Disk**: the laptop's internal drive — it gets wiped. ext4 is fine for a single disk.
- **Country / timezone / keyboard**: yours.
- **Root password / admin email**: pick a strong password, write it down.
- **Network**:
  - Hostname (FQDN): `pve.home.arpa` (or whatever you like, but it must contain a dot)
  - IP Address (CIDR): pick an IP outside your router's DHCP range, e.g. `192.168.0.10/24`
  - Gateway: your router's IP, e.g. `192.168.0.1`
  - DNS Server: same as gateway, or `1.1.1.1`

Confirm and install. ~5 min. Reboot, eject USB.

After reboot the laptop shows a console login. **Ignore it.** Everything from here is in the web UI at:

```
https://192.168.0.10:8006
```

Log in as `root` with the password you set. Dismiss the "no subscription" popup that appears on every login.

## Step 4 — Disable sleep on lid close

This is critical for laptop servers — Linux's default is to suspend when you close the lid.

In Proxmox web UI → click your node (`pve`) on the left → **Shell**:

```bash
nano /etc/systemd/logind.conf
```

Find these three lines (commented out with `#`) and change them to:

```
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`. Apply:

```bash
systemctl restart systemd-logind
```

Test by closing the lid — the laptop should keep running.

## Step 5 — Run the post-install helper script

This disables the enterprise repo (you don't have a subscription), enables the free no-subscription repo, removes the "no subscription" popup, and disables the Corosync HA service (cluster-only, useless on a single node).

In the Proxmox shell:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/post-pve-install.sh)"
```

Answer **Yes** to every prompt. Reboot when it asks.

## Step 6 — Create the Home Assistant OS VM

Same helper-script repository has a one-line installer for HAOS:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/haos-vm.sh)"
```

Pick **Default Settings** (4 GB RAM, 2 cores, 32 GB disk). If your laptop has ≤8 GB RAM, choose Advanced Settings and reduce HAOS to 3 GB.

It downloads HAOS, creates the VM (typically VM 100), and asks if you want to start it. Yes.

Watch VM 100 → Console for HAOS to finish booting (3-5 min). When ready it prints:

```
Home Assistant is now available at: http://192.168.0.X:8123
```

Open that URL.

## Step 7 — HA onboarding

In the browser, do the standard onboarding:

1. Create your admin user
2. Set home location, name, timezone
3. **Skip** the auto-discovered devices step — we add them deliberately later
4. Land on the Overview dashboard

## Step 8 — Reserve IPs in your router

To prevent DHCP from shuffling IPs:

In your router admin → Connected Clients → reserve these IPs by MAC address:

- The Proxmox host (192.168.0.10 in this guide)
- The HAOS VM (whatever it got — find it in the VM 100 Console output)
- The USR-W600 module
- Both Midea ACs, the Mitsubishi outdoor unit if it has Wi-Fi, etc.

Two minutes here saves hours of debugging later.

## Next steps

- [Part 2 — Deploy the Aerogor bridge](02-deploy-bridge.md)
- [Part 3 — Protocol reference](03-protocol-reference.md)
- [Part 4 — Reverse-engineering howto](04-reverse-engineering-howto.md)

## Troubleshooting

**Laptop sleeps when you close the lid despite the logind change:** some laptops have a hardware-level ACPI suspend that fires before Linux sees the lid event. Workaround: leave the lid open, or set the BIOS option if it exists.

**Proxmox boots to a black screen / no console after install:** could be a graphics driver issue. Edit `/etc/default/grub`, add `nomodeset` to `GRUB_CMDLINE_LINUX_DEFAULT`, run `update-grub`, reboot.

**HAOS VM won't start:** check the laptop's BIOS — VT-x/AMD-V must be enabled. Without it, KVM acceleration is unavailable and HAOS won't launch.

**Can't reach HAOS at homeassistant.local:** use the IP directly. mDNS sometimes flakes. The IP is shown on the VM 100 Console screen.
