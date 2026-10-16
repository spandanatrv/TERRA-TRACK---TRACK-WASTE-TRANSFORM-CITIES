# Garbage Truck Digital Twin — Real-Time Mobile GPS Tracking

A full-stack municipal digital twin for smart garbage truck dispatching and live tracking. All simulation logic and artificial coordinate movements have been removed in favor of **real-time mobile phone GPS telemetry**.

---

## Architecture & Features

- **Real Mobile GPS Tracking**: Uses the driver phone's native `navigator.geolocation.watchPosition()` API to transmit actual latitude, longitude, accuracy (in meters), speed, heading, and timestamps.
- **Strict Coordinate Integrity**: Never fabricates truck movement or coordinates. The Leaflet map displays the truck only when valid GPS data is received.
- **Real-Time GPS Status Lifecycle**:
  - `WAITING FOR GPS`: Driver initiated sharing; phone is acquiring satellite lock.
  - `LIVE GPS`: Active high-accuracy GPS fixes streaming (<12s freshness).
  - `LOCATION STALE`: Sharing is active, but no fix received in 12–30s (e.g. tunnel, sky obstruction).
  - `GPS DISCONNECTED`: Driver stopped sharing or phone went offline (>30s).
- **Proximity Alerts**: Automated arrival alerts triggered when the real truck GPS enters a resident's radius (default 300m), saving notifications to SQLite and triggering browser notifications.
- **Route Optimization**: Nearest-neighbor route planning based on resident availability hours.
- **Persistent Data**: SQLite database (`twin.db`) storing residents, availability windows, and notification logs.

---

## Prerequisites & Installation

- Python 3.8+ (tested on Python 3.9+)
- Install dependencies:

```bash
pip install -r requirements.txt
```

*(Zero external bloat — requires only `flask`)*

---

## Running the Application

### 1. Standard Run (HTTP)
```bash
python app.py
```
- Dashboard: [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
- Driver Page: [http://127.0.0.1:5000/driver](http://127.0.0.1:5000/driver)

### 2. HTTPS Run (Required for Direct Phone Wi-Fi GPS)
Modern mobile browsers (Chrome / Safari) strictly block GPS Geolocation over plain HTTP across a network. Run with `--https` to serve using the included self-signed certificates (`cert.pem`, `key.pem`):

```bash
python app.py --https
```
- Dashboard: [https://127.0.0.1:5000/](https://127.0.0.1:5000/)
- Driver Page: `https://<YOUR_LAPTOP_IP>:5000/driver`

*(The server prints your local LAN IP and direct mobile links in the terminal upon startup).*

### Command-Line Options
```bash
python app.py --port 5000 --host 0.0.0.0 [--https]
```

---

## Phone Testing Instructions

### Option A: Chrome USB Port Forwarding (Recommended — Easiest & Zero Warnings)
1. Connect your Android phone to your laptop via USB cable (with USB Debugging enabled).
2. In Chrome on your laptop, navigate to:
   ```
   chrome://inspect/#devices
   ```
3. Click **Port forwarding...**, then add:
   - Port: `5000`
   - IP address and port: `localhost:5000`
   - Check **Enable port forwarding** and click **Done**.
4. On your phone's Chrome browser, open:
   ```
   http://localhost:5000/driver
   ```
   *Because `localhost` is treated as a secure origin, GPS permissions work instantly without HTTPS certificate warnings.*
5. Tap **Start Sharing Location**.

---

### Option B: Local Wi-Fi with HTTPS
1. Ensure both your phone and laptop are connected to the same Wi-Fi network.
2. Start the server with HTTPS:
   ```bash
   python app.py --https
   ```
3. Note your laptop's local IP printed in the console (e.g. `192.168.1.15`).
4. On your mobile browser, open:
   ```
   https://<YOUR_LAPTOP_IP>:5000/driver
   ```
5. Tap **Advanced** &rarr; **Proceed to IP (unsafe)** to accept the self-signed certificate.
6. Tap **Start Sharing Location** and allow browser location access when prompted.

---

### Option C: Browser GPS Sensor Emulation (Laptop Testing)
1. Open [http://127.0.0.1:5000/driver](http://127.0.0.1:5000/driver) in Chrome.
2. Open DevTools (`F12`), press `Ctrl+Shift+P`, type **Sensors**, and press Enter.
3. In the **Location** dropdown, select **Other...** and enter coordinates (e.g. `12.9352, 77.5350`).
4. Click **Start Sharing Location** to stream real `watchPosition()` updates.

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Web dashboard with interactive Leaflet map & planner |
| `/driver` | `GET` | Mobile driver terminal for real-time GPS broadcasting |
| `/api/truck` | `GET` | Fetches live truck state, GPS status, telemetry, route, and alerts |
| `/api/truck/location` | `POST` | Ingests real GPS payload (`lat`, `lon`, `accuracy`, `speed`, `heading`, `timestamp`) |
| `/api/truck/start_gps` | `POST` | Signals driver started location sharing (`WAITING FOR GPS`) |
| `/api/truck/stop_gps` | `POST` | Signals driver stopped location sharing (`GPS DISCONNECTED`) |
| `/api/truck/start` | `POST` | Dispatches optimal pickup window (`start`, `len`) |
| `/api/truck/stop` | `POST` | Halts the active dispatch run |
| `/api/residents` | `GET`, `POST` | Lists all households or registers a new household |
| `/api/residents/<id>` | `DELETE` | Removes a registered household |
| `/api/schedule` | `GET` | Computes optimal collection windows based on resident hours |
| `/api/seed` | `POST` | Seeds 25 demo households with realistic availability |
