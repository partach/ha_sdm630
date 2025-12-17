"""Constants for the Eastron SDM630 integration."""
from typing import Dict

DOMAIN = "HA-SDM630"

CONF_SERIAL_PORT = "serial_port"
CONF_SLAVE_ID = "slave_id"
CONF_BAUDRATE = "baudrate"
CONF_NAME = "name"
CONF_REGISTER_SET = "register_set"

DEFAULT_SLAVE_ID = 1
DEFAULT_BAUDRATE = 9600
DEFAULT_REGISTER_SET = "basic"

# Register set options
REGISTER_SET_BASIC = "basic"
REGISTER_SET_BASIC_PLUS = "basic_plus"
REGISTER_SET_FULL = "full"

# Define the three register sets
_BASIC_REGISTERS = {
    # Essential sensors – fast polling
    "phase_1_l_n_volts": {"address": 0, "name": "Phase 1 L/N Volts", "unit": "V", "device_class": "voltage", "state_class": "measurement", "precision": 2},
    "phase_2_l_n_volts": {"address": 2, "name": "Phase 2 L/N Volts", "unit": "V", "device_class": "voltage", "state_class": "measurement", "precision": 2},
    "phase_3_l_n_volts": {"address": 4, "name": "Phase 3 L/N Volts", "unit": "V", "device_class": "voltage", "state_class": "measurement", "precision": 2},
    "phase_1_current": {"address": 6, "name": "Phase 1 Current", "unit": "A", "device_class": "current", "state_class": "measurement", "precision": 2},
    "phase_2_current": {"address": 8, "name": "Phase 2 Current", "unit": "A", "device_class": "current", "state_class": "measurement", "precision": 2},
    "phase_3_current": {"address": 10, "name": "Phase 3 Current", "unit": "A", "device_class": "current", "state_class": "measurement", "precision": 2},
    "phase_1_power": {"address": 12, "name": "Phase 1 Power", "unit": "W", "device_class": "power", "state_class": "measurement", "precision": 2},
    "phase_2_power": {"address": 14, "name": "Phase 2 Power", "unit": "W", "device_class": "power", "state_class": "measurement", "precision": 2},
    "phase_3_power": {"address": 16, "name": "Phase 3 Power", "unit": "W", "device_class": "power", "state_class": "measurement", "precision": 2},
    "total_system_power": {"address": 52, "name": "Total Power", "unit": "W", "device_class": "power", "state_class": "measurement", "precision": 2},
    "frequency": {"address": 70, "name": "Frequency", "unit": "Hz", "device_class": "frequency", "state_class": "measurement", "precision": 2},
    "import_energy": {"address": 72, "name": "Import Energy", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "precision": 2},
    "export_energy": {"address": 74, "name": "Export Energy", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "precision": 2},
    "total_kwh": {"address": 342, "name": "Total kWh", "unit": "kWh", "device_class": "energy", "state_class": "total", "precision": 2},
}
_BASIC_PLUS_REGISTERS = {
    # Everything from basic + more useful ones
    **_BASIC_REGISTERS,
    "phase_1_volt_amps": {"address": 18, "name": "Phase 1 VA", "unit": "VA", "device_class": "apparent_power", "state_class": "measurement", "precision": 2},
    "phase_2_volt_amps": {"address": 20, "name": "Phase 2 VA", "unit": "VA", "device_class": "apparent_power", "state_class": "measurement", "precision": 2},
    "phase_3_volt_amps": {"address": 22, "name": "Phase 3 VA", "unit": "VA", "device_class": "apparent_power", "state_class": "measurement", "precision": 2},
    "phase_1_power_factor": {"address": 30, "name": "Phase 1 Power Factor", "unit": None, "device_class": "power_factor", "state_class": "measurement", "precision": 3},
    "phase_2_power_factor": {"address": 32, "name": "Phase 2 Power Factor", "unit": None, "device_class": "power_factor", "state_class": "measurement", "precision": 3},
    "phase_3_power_factor": {"address": 34, "name": "Phase 3 Power Factor", "unit": None, "device_class": "power_factor", "state_class": "measurement", "precision": 3},
    "neutral_current": {"address": 224, "name": "Neutral Current", "unit": "A", "device_class": "current", "state_class": "measurement", "precision": 2},
    "line_1_to_line_2_volts": {"address": 200, "name": "Line 1 to Line 2 Volts", "unit": "V", "device_class": "voltage", "state_class": "measurement", "precision": 2},
    "line_2_to_line_3_volts": {"address": 202, "name": "Line 2 to Line 3 Volts", "unit": "V", "device_class": "voltage", "state_class": "measurement", "precision": 2},
    "line_3_to_line_1_volts": {"address": 204, "name": "Line 3 to Line 1 Volts", "unit": "V", "device_class": "voltage", "state_class": "measurement", "precision": 2},
    # Add more as you want
}
_FULL_REGISTERS = {
    # All registers from your long list – you can copy them all here
    **_BASIC_PLUS_REGISTERS,
    # Paste all the remaining ones from your YAML (THD, demand, per-phase energy, etc.)
    # Example:
    "phase_1_l_n_volts_thd": {"address": 234, "name": "Phase 1 L/N Volts THD", "unit": "%", "state_class": "measurement", "precision": 2},
    # ... all the rest
}
REGISTER_SETS = {
    REGISTER_SET_BASIC: _BASIC_REGISTERS,
    REGISTER_SET_BASIC_PLUS: _BASIC_PLUS_REGISTERS,
    REGISTER_SET_FULL: _FULL_REGISTERS,
}

