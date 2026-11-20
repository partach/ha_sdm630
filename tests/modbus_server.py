"""Simulated SDM630 for the tests: python modbus_server.py PORT [socket|rtu] [full|sparse].

"full" answers every address; "sparse" only the addresses the integration defines,
like a meter that rejects reads spanning unused registers.
"""

import asyncio
import struct
import sys

from pymodbus import FramerType
from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSparseDataBlock,
)
from pymodbus.server import StartAsyncTcpServer

sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
from custom_components.ha_sdm630.const import REGISTER_SETS

VALUES = {
    "total_system_power": -2500.0,
    "phase_1_power": -850.5,
    "import_energy": 0.0,
    "export_energy": 15422.1,
    "phase_1_volt_amps_reactive": 100.0,
    "phase_2_volt_amps_reactive": 200.0,
    "phase_3_volt_amps_reactive": 300.0,
    "total_system_var": 600.0,
}
DEFAULT_VALUE = 230.0
# Store this register with its two words swapped, as seen on some meters
SWAPPED = {"total_system_var"}


def registers() -> dict[int, int]:
    regs: dict[int, int] = {}
    for key, info in REGISTER_SETS["full"].items():
        high, low = struct.unpack(">HH", struct.pack(">f", VALUES.get(key, DEFAULT_VALUE)))
        if key in SWAPPED:
            high, low = low, high
        regs[info["address"]] = high
        regs[info["address"] + 1] = low
    return regs


def main() -> None:
    port = int(sys.argv[1])
    framer = FramerType.RTU if sys.argv[2:3] == ["rtu"] else FramerType.SOCKET
    sparse = sys.argv[3:4] == ["sparse"]
    regs = registers()
    if sparse:
        block = ModbusSparseDataBlock(dict(regs))
    else:
        # Sequential blocks are offset by one in pymodbus' device context
        block = ModbusSequentialDataBlock(1, [regs.get(addr, 0) for addr in range(400)])
    context = ModbusServerContext(devices=ModbusDeviceContext(ir=block), single=True)
    asyncio.run(StartAsyncTcpServer(context=context, address=("127.0.0.1", port), framer=framer))


if __name__ == "__main__":
    main()
