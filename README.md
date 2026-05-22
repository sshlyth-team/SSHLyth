# SSHlyth

A web-based SSH client for Synology DSM 7, accessible directly from your browser.

![SSHlyth](https://img.shields.io/badge/DSM-7.0%2B-blue) ![Version](https://img.shields.io/badge/version-3.1.3-green) ![License](https://img.shields.io/badge/license-Custom-lightgrey)

---

## Features

- Full terminal emulator that supports interactive programs (vi, nano, htop, etc.)
- DSM-based authentication or using DSM credentials (port 7722)
- HTTPS on port 7722 with auto-generated certificate
- Accessible via your NAS address through nginx reverse proxy (`/SSHlyth/`) — the nginx setup commands are provided openly so you can review and run them yourself, with no hidden system modifications
- Real-time bidirectional communication via WebSockets.
- Command history with arrow keys (up to 200 entries)
- DSM main menu icon

---

## Requirements

- Synology DSM 7.0 or later
- Python 3.x package installed (any version: Python 3.8, 3.9, 3.10, 3.11)

---

## Installation

1. Download the latest `.spk` from the [Releases](../../releases) page
2. Open **Package Center** in DSM
3. Click **Manual Install** and upload the `.spk`
4. Follow the prompts — DSM will ask whether to open port 7722 in the firewall

> **Note:** Python 3.x must be installed before SSHlyth. If it is not present, install it first from Package Center.

---

## Access

### Option 1 — Direct HTTPS (port 7722)

```
https://your-nas-address:7722/
```

SSHlyth generates a self-signed certificate on first start. Your browser will show a security warning — accept it once and it will not appear again.
In order to avoid unautenticate use of the ssh client authentication is mandatory. SSHlyth cannot reuse the DSM session in this mode. A login form will appear asking for your DSM username and password. Only users with valid DSM credentials can proceed.

### Option 2 — From the DSM main menu (nginx reverse proxy setup)

```
https://your-nas-address/SSHlyth/
```

This feature leverages the existing DSM session, eliminating browser warnings and the need for additional authentication.
A one-time Nginx setup is required after installation. See the Nginx Setup section for details.

This functionality is available when the Nginx reverse proxy is configured (Option 2 above).

---

## Nginx Setup (Option 2)

After installing the package, run the following two commands on your NAS as root (or create a **Scheduled Task** in DSM Control Panel → Task Scheduler, run with sudo):

```sh
sudo cp /var/packages/sshlyth/target/nginx-location.conf /etc/nginx/conf.d/dsm.sshlyth.conf
sudo kill -HUP $(cat /run/nginx.pid)
```
This script configures Nginx to redirect traffic to your-nas-address/SSHlyth/.
The commands only need to be run once after installation, or after a DSM update that resets the Nginx configuration.
---


## Tested Systems

SSHlyth has been tested on the following hardware and firmware:

| Hardware | DSM Version |
|----------|-------------|
| Synology DS220+ | DSM 7.3.2 |

If you have tested SSHlyth on other hardware or DSM versions, feedback is welcome. For installation issues or general support, send an email to [sshlyth@clustarion.com](mailto:sshlyth@clustarion.com).

---

## Stack

| Component | Technology |
|-----------|------------|
| Backend   | Python 3 + Flask + Flask-SocketIO |
| SSH       | paramiko |
| Terminal  | xterm.js 5.3 |
| Transport | WebSocket (simple-websocket) |
| Port      | 7722 (HTTPS) |

---

## License

See [LICENSE](LICENSE) for details.

Summary: Free for personal use. If you plan to make money with it, contact us first at [sshlyth@clustarion.com](mailto:sshlyth@clustarion.com).
