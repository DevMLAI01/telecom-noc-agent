# =============================================================================
# data/mock_telemetry.py
# =============================================================================
# Purpose: Simulates a live Network Management System (NMS) database.
# In a real NOC environment, this would be replaced by API calls to systems
# like Cisco NSO, Nokia NetAct, or a proprietary NMS REST endpoint.
# Each alarm_id maps to a dictionary of real-time network vitals that a
# Level 3 engineer would review during an incident triage.
# =============================================================================

MOCK_NETWORK_TELEMETRY: dict[str, dict] = {
    # -------------------------------------------------------------------------
    # ALARM-001: DOCSIS 3.1 CMTS Upstream Impairment
    # Scenario: Arris E6000 CMTS is seeing T3 timeout floods on US channel.
    # Root cause suspected: upstream noise ingress from a faulty tap/amplifier.
    # -------------------------------------------------------------------------
    "ALARM-001": {
        "alarm_id": "ALARM-001",
        "device": "Arris E6000 CMTS",
        "location": "Headend-Chicago-01",
        "severity": "CRITICAL",
        "error_type": "DOCSIS T3 Timeout",
        "upstream_channel": "US-CH-6 (37.4 MHz)",
        "t3_timeout_count_last_hour": 1482,
        "t4_timeout_count_last_hour": 23,
        "upstream_rx_power_dbmv": -2.5,       # Nominal range: -10 to +10 dBmV
        "upstream_snr_db": 21.4,              # Alarm threshold: < 25 dB
        "corrected_errors_pct": 18.7,         # Alarm threshold: > 5%
        "uncorrectable_errors_pct": 4.2,      # Alarm threshold: > 1%
        "affected_modems_count": 347,
        "modulation_profile": "ATDMA 64-QAM", # Degraded from 256-QAM
        "cmts_cpu_utilization_pct": 42,
        "cmts_memory_utilization_pct": 68,
        "timestamp": "2026-02-26T08:14:32Z",
    },

    # -------------------------------------------------------------------------
    # ALARM-002: Nokia Fiber ONU Rx Power Degradation
    # Scenario: Nokia GPON OLT reporting low optical Rx on a specific ONU.
    # Root cause suspected: dirty/damaged fiber connector or fiber bend.
    # -------------------------------------------------------------------------
    "ALARM-002": {
        "alarm_id": "ALARM-002",
        "device": "Nokia 7360 ISAM FX OLT",
        "location": "CO-Dallas-03",
        "severity": "MAJOR",
        "error_type": "GPON ONU Rx Power Low",
        "olt_port": "GPON-1/1/4",
        "onu_serial_number": "NOKIA-A3F2C1D9",
        "onu_model": "Nokia G-240W-A",
        "rx_power_dbm": -28.9,               # Alarm threshold: < -28.0 dBm
        "tx_power_dbm": 2.1,                 # Nominal: +2 to +4 dBm
        "ber_downstream": "1.2e-4",          # Alarm threshold: > 1e-6
        "ber_upstream": "3.5e-5",
        "optical_path_loss_db": 31.0,        # Budget exceeded (max 28 dB)
        "wavelength_downstream_nm": 1490,
        "wavelength_upstream_nm": 1310,
        "affected_subscribers": 1,
        "service_type": "Residential 1Gbps",
        "timestamp": "2026-02-26T09:02:11Z",
    },

    # -------------------------------------------------------------------------
    # ALARM-003: BGP Route Flap on Core Router
    # Scenario: Cisco ASR9K experiencing BGP session instability with peer.
    # Root cause suspected: MTU mismatch or physical link instability.
    # -------------------------------------------------------------------------
    "ALARM-003": {
        "alarm_id": "ALARM-003",
        "device": "Cisco ASR9001 Core Router",
        "location": "POP-NewYork-Hub-01",
        "severity": "CRITICAL",
        "error_type": "BGP Session Flap",
        "bgp_peer_ip": "203.0.113.1",
        "bgp_peer_as": "AS64512",
        "bgp_session_state": "IDLE",
        "flap_count_last_hour": 14,
        "hold_time_seconds": 90,
        "keepalive_interval_seconds": 30,
        "routes_received_before_flap": 892341,
        "interface": "HundredGigE0/0/0/1",
        "interface_errors_last_hour": 2847,
        "interface_crc_errors": 1923,
        "mtu_local": 9000,                   # Jumbo frames configured
        "mtu_peer_reported": 1500,           # MTU mismatch detected!
        "cpu_process_bgp_pct": 78,           # Elevated CPU
        "timestamp": "2026-02-26T07:45:00Z",
    },

    # -------------------------------------------------------------------------
    # ALARM-004: Juniper MX Series High Traffic Congestion
    # Scenario: Juniper MX480 experiencing packet drops on edge interface.
    # Root cause suspected: traffic burst exceeding interface queue capacity.
    # -------------------------------------------------------------------------
    "ALARM-004": {
        "alarm_id": "ALARM-004",
        "device": "Juniper MX480 Edge Router",
        "location": "Edge-LA-02",
        "severity": "MAJOR",
        "error_type": "Interface Queue Congestion",
        "interface": "xe-0/0/2",
        "interface_speed_gbps": 10,
        "current_traffic_gbps": 9.87,        # 98.7% utilization
        "packet_drop_rate_pps": 45230,
        "queue_depth_pct": 97.3,
        "output_errors_last_hour": 128904,
        "tail_drop_count": 89452,
        "cos_queue_0_drop_pct": 0.2,
        "cos_queue_7_drop_pct": 34.1,        # High priority drops!
        "top_talker_ip": "192.0.2.45",
        "top_talker_traffic_gbps": 3.2,
        "timestamp": "2026-02-26T10:30:00Z",
    },
}


def get_telemetry_for_alarm(alarm_id: str) -> dict:
    """
    Retrieves mock live telemetry data for a given alarm ID.

    Args:
        alarm_id: The unique identifier of the network alarm (e.g., 'ALARM-001').

    Returns:
        A dictionary of live network vitals, or an error dict if not found.
    """
    if alarm_id in MOCK_NETWORK_TELEMETRY:
        return MOCK_NETWORK_TELEMETRY[alarm_id]
    else:
        return {
            "error": f"No telemetry found for alarm_id: {alarm_id}",
            "available_alarms": list(MOCK_NETWORK_TELEMETRY.keys()),
        }
