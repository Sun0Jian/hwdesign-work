"""Waveflow HostActivated boundary for the signed 16-bit max-pool body."""

from dataclasses import dataclass, field
from typing import ClassVar

from waveflow.hw.dataschema import IntField
from waveflow.hw.hw_hostactivated import HostActivated
from waveflow.hw.interface import StreamIFMaster, StreamIFSlave
from waveflow.hw.regmap import (
    Bit, RegAccess, RegField, VitisRegMap, VitisRegMapMMIFSlave,
)

UInt32 = IntField.specialize(bitwidth=32, signed=False)


@dataclass
class MaxPoolAccel(HostActivated):
    """Fixed 32-bit streaming ports and status-only AXI-Lite registers."""

    cpp_kernel_name: ClassVar[str] = "maxpool"
    cpp_namespace: ClassVar[str] = "maxpool_impl"
    cpp_body: ClassVar[str] = "body"

    clk_freq: float = 100e6
    aximm_bw: int = 32
    s_in: StreamIFSlave = field(init=False)
    m_out: StreamIFMaster = field(init=False)
    s_lite: VitisRegMapMMIFSlave = field(init=False)
    regmap: VitisRegMap = field(init=False)

    def __post_init__(self):
        super().__post_init__()
        self.s_in = StreamIFSlave(
            name=f"{self.name}_s_in", sim=self.sim, bitwidth=32,
        )
        self.m_out = StreamIFMaster(
            name=f"{self.name}_m_out", sim=self.sim, bitwidth=32,
        )
        self.regmap = VitisRegMap(
            {
                "halted": RegField(Bit, RegAccess.R, description="1=halted"),
                "error": RegField(UInt32, RegAccess.R, description="error code"),
                "error_tx_id": RegField(
                    UInt32, RegAccess.R, description="offending transaction ID",
                ),
            },
            bitwidth=self.aximm_bw,
        )
        self.s_lite = VitisRegMapMMIFSlave(
            name=f"{self.name}_s_lite", sim=self.sim, bitwidth=self.aximm_bw,
            regmap=self.regmap, on_start=self.on_start,
        )
        self.add_endpoint(self.s_in)
        self.add_endpoint(self.m_out)
        self.add_endpoint(self.s_lite)
