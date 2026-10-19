"""Constants for Glow History Import."""

DOMAIN = "glow_history"

API_BASE = "https://api.glowmarkt.com/api/v0-1"
# Public application ID used by Hildebrand's Bright app.
APPLICATION_ID = "b0f1b774-a586-4f72-9edd-27ead8aa7a8d"

# fuel key -> Glowmarkt resource classifier
FUELS = {
    "electricity": "electricity.consumption",
    "gas": "gas.consumption",
}

CONF_ELEC_RATE = "electricity_unit_rate"
CONF_ELEC_STANDING = "electricity_standing_charge"
CONF_GAS_RATE = "gas_unit_rate"
CONF_GAS_STANDING = "gas_standing_charge"
CONF_INCLUDE_STANDING = "include_standing_charge"
CONF_SCAN_HOURS = "scan_interval_hours"
CONF_LOOKBACK_DAYS = "lookback_days"
CONF_BACKFILL_DAYS = "backfill_days"

DEFAULT_OPTIONS = {
    CONF_ELEC_RATE: 24.47,  # p/kWh
    CONF_ELEC_STANDING: 47.81,  # p/day
    CONF_GAS_RATE: 7.64,  # p/kWh
    CONF_GAS_STANDING: 29.16,  # p/day
    CONF_INCLUDE_STANDING: True,
    CONF_SCAN_HOURS: 3,
    CONF_LOOKBACK_DAYS: 7,
    CONF_BACKFILL_DAYS: 395,
}

RATE_KEYS = {
    "electricity": (CONF_ELEC_RATE, CONF_ELEC_STANDING),
    "gas": (CONF_GAS_RATE, CONF_GAS_STANDING),
}

# Glowmarkt allows at most ~10 days per PT30M request; stay well inside that.
CHUNK_DAYS = 7
