from cocotb.utils import hexdump
from cocotb.decorators import coroutine
from cocotb.monitors import BusMonitor
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly
from cocotb.fixedpoint import FXfamily, FXnum


class AxisSlave(BusMonitor):
    """
    Packetised AvalonST bus
    """
    _signals = ["tvalid", "tdata"]
    _optional_signals = ["tready", "tlast"]

    def __init__(self, *args, **kwargs):
        self.dtype = kwargs.pop('dtype',int)
        self.pkg_size = kwargs.pop('pkg_size',16)
        BusMonitor.__init__(self, *args, **kwargs)
        self.pkt = list()

    @coroutine
    def package_finished(self):
        self.log.info("Received a packet of %d words" % len(self.pkt))
        if self._event is not None:
            yield self._event.wait()
        self._recv(self.pkt)
        self.pkt = list()

    @coroutine
    def _monitor_recv(self):
        """Watch the pins and reconstruct transactions"""

        # Avoid spurious object creation by recycling
        clkedge = RisingEdge(self.clock)
        negclk = FallingEdge(self.clock)
        rdonly = ReadOnly()
        self.pkt = list()

        def tvalid():
            if hasattr(self.bus, 'tready'):
                return self.bus.tvalid.value and self.bus.tready.value
            return self.bus.tvalid.value

        while True:
            yield clkedge
            yield rdonly
            if self.in_reset:
                continue
            if tvalid():
                if isinstance(self.dtype, FXfamily):
                    word = FXnum(0.0,self.dtype)
                    word.scaledval = self.bus.tdata.value.signed_integer
                    self.pkt.append(word)
                else:
                    word = self.dtype(self.bus.tdata.value)
                    self.pkt.append(word)

                if hasattr(self.bus, 'tlast'):
                    if self.bus.tlast.value:
                        yield self.package_finished()
                elif self.pkg_size == len(self.pkt):
                    yield self.package_finished()
