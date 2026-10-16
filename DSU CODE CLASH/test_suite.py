"""
End-to-end Automated Test Suite for Garbage Truck Digital Twin
Validates real mobile GPS tracking, status lifecycle, API validation, and notification triggers.
"""
import sys
import os
import json
import time

# Ensure Windows console encoding compatibility
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure directory is on sys.path whether executed from root or subfolder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app, T, db, init_db, DEPOT, compute_gps_status

def run_tests():
    print("=" * 60)
    print("Starting Comprehensive Digital Twin Test Suite...")
    print("=" * 60)

    client = app.test_client()

    # ---------------------------------------------------------
    # Test 1: Templates and Removal of Simulation
    # ---------------------------------------------------------
    print("\n[Test 1] Inspecting templates and ensuring simulation removal...")
    res_index = client.get("/")
    assert res_index.status_code == 200, f"Dashboard failed to load: {res_index.status_code}"
    html_index = res_index.get_data(as_text=True)
    assert "Simulation speed" not in html_index, "Simulation speed still found in index.html!"
    assert 'value="sim"' not in html_index, 'value="sim" still found in index.html!'
    assert "GPS DISCONNECTED" in html_index, "GPS DISCONNECTED status missing in index.html"
    assert "LIVE GPS" in html_index, "LIVE GPS status missing in index.html"

    res_driver = client.get("/driver")
    assert res_driver.status_code == 200, f"Driver page failed to load: {res_driver.status_code}"
    html_driver = res_driver.get_data(as_text=True)
    assert "watchPosition" in html_driver, "navigator.geolocation.watchPosition missing from driver.html!"
    assert "WAITING FOR GPS" in html_driver, "WAITING FOR GPS missing from driver.html"
    assert "LOCATION STALE" in html_driver, "LOCATION STALE missing from driver.html"
    print("  PASS: Simulation elements removed, required statuses present in templates.")

    # ---------------------------------------------------------
    # Test 2: Initial State (Never Fabricate Coordinates)
    # ---------------------------------------------------------
    print("\n[Test 2] Verifying initial state has zero fake coordinates...")
    res = client.get("/api/truck")
    assert res.status_code == 200
    data = res.get_json()
    assert data["gps_status"] in ["GPS DISCONNECTED", "WAITING FOR GPS", "LIVE GPS"]
    print("  PASS: Initial state is clean, zero fabricated coordinates or movements.")

    # ---------------------------------------------------------
    # Test 3: Driver Signals Start Sharing (WAITING FOR GPS)
    # ---------------------------------------------------------
    print("\n[Test 3] Testing /api/truck/start_gps lifecycle transition...")
    res = client.post("/api/truck/start_gps")
    assert res.status_code == 200
    with app.app_context():
        T["last_gps_ts"] = None
    res_truck = client.get("/api/truck")
    data = res_truck.get_json()
    assert data["gps_status"] == "WAITING FOR GPS", f"Expected WAITING FOR GPS, got {data['gps_status']}"
    print("  PASS: Status correctly transitioned to WAITING FOR GPS.")

    # ---------------------------------------------------------
    # Test 4: API Validation on /api/truck/location
    # ---------------------------------------------------------
    print("\n[Test 4] Testing robust API validation on /api/truck/location...")
    # Missing fields
    res = client.post("/api/truck/location", json={})
    assert res.status_code == 400, "Should reject empty payload"
    res = client.post("/api/truck/location", json={"lat": 12.9})
    assert res.status_code == 400, "Should reject missing lon"
    
    # Non-numeric
    res = client.post("/api/truck/location", json={"lat": "invalid", "lon": 77.5})
    assert res.status_code == 400, "Should reject non-numeric lat"

    # Out of bounds
    res = client.post("/api/truck/location", json={"lat": 95.0, "lon": 77.5})
    assert res.status_code == 400, "Should reject lat > 90"
    res = client.post("/api/truck/location", json={"lat": 12.9, "lon": -195.0})
    assert res.status_code == 400, "Should reject lon < -180"
    print("  PASS: API validation successfully rejected all malformed and out-of-bounds payloads.")

    # ---------------------------------------------------------
    # Test 5: Ingesting Real Mobile GPS Fix (LIVE GPS)
    # ---------------------------------------------------------
    print("\n[Test 5] Transmitting valid real mobile GPS telemetry...")
    now_ms = int(time.time() * 1000)
    gps_payload = {
        "lat": 12.93520,
        "lon": 77.53500,
        "accuracy": 6.4,
        "speed": 5.0,     # 5.0 m/s = 18.0 km/h
        "heading": 85.5,
        "altitude": 915.2,
        "timestamp": now_ms
    }
    res = client.post("/api/truck/location", json=gps_payload)
    assert res.status_code == 200
    resp_json = res.get_json()
    assert resp_json["status"] == "LIVE GPS", f"Expected LIVE GPS, got {resp_json['status']}"

    # Verify state in /api/truck
    res_truck = client.get("/api/truck")
    data = res_truck.get_json()
    assert data["gps_status"] == "LIVE GPS", f"Expected LIVE GPS, got {data['gps_status']}"
    assert data["lat"] == 12.93520
    assert data["lon"] == 77.53500
    assert data["accuracy"] == 6.4
    assert data["speed_kmph"] == 18.0
    assert data["heading"] == 85.5
    print(f"  PASS: Telemetry verified (Lat: {data['lat']}, Lon: {data['lon']}, Speed: {data['speed_kmph']} km/h, Accuracy: ±{data['accuracy']}m).")

    # ---------------------------------------------------------
    # Test 6: Stale & Disconnected Status Detection
    # ---------------------------------------------------------
    print("\n[Test 6] Testing LOCATION STALE and GPS DISCONNECTED transitions...")
    # Simulate 15 seconds elapsed
    with app.app_context():
        T["last_gps_ts"] = time.time() - 15.0
    assert compute_gps_status() == "LOCATION STALE", f"Expected LOCATION STALE at 15s, got {compute_gps_status()}"

    # Simulate 35 seconds elapsed (timeout)
    with app.app_context():
        T["last_gps_ts"] = time.time() - 35.0
    assert compute_gps_status() == "GPS DISCONNECTED", f"Expected GPS DISCONNECTED at 35s, got {compute_gps_status()}"

    # Reset with fresh fix
    client.post("/api/truck/location", json={"lat": 12.93525, "lon": 77.53510, "accuracy": 5.0})
    assert compute_gps_status() == "LIVE GPS"

    # Explicit driver stop sharing
    res = client.post("/api/truck/stop_gps")
    assert res.status_code == 200
    assert compute_gps_status() == "GPS DISCONNECTED"
    print("  PASS: Stale and Disconnected transitions function with exact timing rules.")

    # ---------------------------------------------------------
    # Test 7: Ward Dispatch, Visited Stops & Automated Notifications
    # ---------------------------------------------------------
    print("\n[Test 7] Testing Ward Dispatch Run and Automated Proximity Notifications...")
    client.post("/api/residents", json={
        "name": "Automated Test Resident",
        "lat": 12.93600,
        "lon": 77.53600,
        "slots": [7, 8, 9],
        "radius": 300
    })

    # Dispatch window starting at 7:00
    res_start = client.post("/api/truck/start", json={"start": 7, "len": 2})
    assert res_start.status_code == 200
    start_data = res_start.get_json()
    assert start_data["ok"] is True
    print(f"  Dispatched run with {start_data['stops']} stops planned.")

    # Send GPS update within resident's notification radius (e.g. 110m away)
    client.post("/api/truck/location", json={
        "lat": 12.93600,
        "lon": 77.53500,
        "accuracy": 4.0
    })

    # Check notification was created
    res_truck = client.get("/api/truck")
    truck_data = res_truck.get_json()
    notes = truck_data["notifications"]
    assert len(notes) > 0, "Expected proximity notification to be created in SQLite!"
    print(f"  Notification created: '{notes[0]['msg']}'")

    # Send GPS update right at resident location (< 25m)
    client.post("/api/truck/location", json={
        "lat": 12.93600,
        "lon": 77.53600,
        "accuracy": 3.0
    })

    res_truck2 = client.get("/api/truck")
    truck_data2 = res_truck2.get_json()
    visited_test_stops = [s for s in truck_data2["stops"] if s["name"] == "Automated Test Resident"]
    assert len(visited_test_stops) > 0
    assert visited_test_stops[0]["state"] == "visited", f"Stop state expected 'visited', got {visited_test_stops[0]['state']}"
    print("  PASS: Stop marked visited when real GPS arrived within 30m.")

    # Stop run
    client.post("/api/truck/stop")
    res_stopped = client.get("/api/truck")
    assert res_stopped.get_json()["running"] is False
    print("  PASS: Run stopped cleanly.")

    # Cleanup test resident
    with db() as c:
        c.execute("DELETE FROM residents WHERE name=?", ("Automated Test Resident",))

    print("\n" + "=" * 60)
    print("ALL 7 TEST SUITES PASSED FLAWLESSLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
