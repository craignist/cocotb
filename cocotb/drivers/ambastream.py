import cocotb

from cocotb.decorators import coroutine
from cocotb.triggers import RisingEdge
from cocotb.triggers import ReadOnly
from cocotb.drivers import ValidatedBusDriver
from cocotb.utils import hexdump
from cocotb.binary import BinaryValue
from cocotb.fixedpoint import FXfamily, FXnum


class AxisMaster(ValidatedBusDriver):
    _signals = ["tvalid", "tdata"]
    _optional_signals = ["tready", "tlast"]

    def __init__(self, *args, **kwargs):
        self.dtype = kwargs.pop('dtype',int)
        ValidatedBusDriver.__init__(self, *args, **kwargs)

        word = BinaryValue(bits=len(self.bus.tdata), bigEndian=False)

        single = BinaryValue(bits=1)

        word.binstr = ("x" * len(self.bus.tdata))
        single.binstr = ("x")

        self.bus.tvalid <= 0
        self.bus.tdata <= 0
        self.bus.tlast <= 0
        self.log.info("Initializing AXIS Driver")

    @coroutine
    def _wait_ready(self):
        yield ReadOnly()
        while not self.bus.tready.value:
            yield RisingEdge(self.clock)
            yield ReadOnly()

    @coroutine
    def _driver_send(self, pkt, sync=True):
        """
        Args:
            string (str): A string of bytes to send over the bus
        """
        self.log.info("Sending packet of length %d words" % len(pkt))

        # Avoid spurious object creation by recycling
        clkedge = RisingEdge(self.clock)
        firstword = True

        word = BinaryValue(bits=len(self.bus.tdata), bigEndian=False)
        single = BinaryValue(bits=1)

        # Drive some defaults since we don't know what state we're in
        #self.bus.tvalid <= 0
        count = len(pkt)

        for cur_word in pkt:
            #if not firstword or (firstword and sync):
            #    yield clkedge

            if hasattr(self.bus, "tlast"):
                count -= 1
                if count == 0:
                    self.bus.tlast <= 1
                else:
                    self.bus.tlast <= 0

            # Insert a gap where tvalid is low
            if not self.on:
                self.bus.tvalid <= 0
                for i in range(self.off):
                    yield clkedge

                # Grab the next set of on/off values
                self._next_valids()

            # Consume a tvalid cycle
            if self.on is not True and self.on:
                self.on -= 1

            self.bus.tvalid <= 1

            if firstword:
                firstword = False

            if isinstance(self.dtype, FXfamily):
                try :
                    word.integer = self.dtype(cur_word)._toTwosComplement()[0]
                except:
                    self.log.error("Overflow error fitting %f into %s" % (cur_word, str(self.dtype)))
                    raise
            else:
                word.integer = cur_word

            self.bus.tdata <= word

            # If this is a bus with a ready signal, wait for this word to
            # be acknowledged
            if hasattr(self.bus, "tready"):
                yield self._wait_ready()

            yield clkedge
        self.log.info("Sucessfully sent packet of length %d bytes" % len(pkt))
