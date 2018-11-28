''' Copyright (c) 2013 Potential Ventures Ltd
Copyright (c) 2013 SolarFlare Communications Inc
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of Potential Ventures Ltd,
      SolarFlare Communications Inc nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL POTENTIAL VENTURES LTD BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE. '''

import random
import logging

import cocotb
import numpy as np

from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, Event
from cocotb.drivers import BitDriver
from cocotb.drivers.ambastream import AxisMaster
from cocotb.monitors.ambastream import AxisSlave
from cocotb.regression import TestFactory
from cocotb.scoreboard import Scoreboard
from cocotb.result import TestFailure, raise_error
from cocotb.fixedpoint import FXnum, FXfamily, FXoverflowError


# Data generators
from cocotb.generators.byte import random_data, get_bytes
from cocotb.generators.bit import (wave, intermittent_single_cycles,
                                   random_50_percent)


class EndianSwapperTB(object):

    def __init__(self, dut, clk, reset, latency, debug=False):
        self.dut = dut
        self.aclk = clk
        self.aresetn = reset
        self.axis_tdata_size = dut.AXIS_TDATA_WIDTH
        self.latch_type = dut.REG_TYPE
        #fptype_in=FXfamily(6,2)
        #fptype_out=FXfamily(6,2)
        fptype_in=int
        fptype_out=int
        self.stream_in = AxisMaster(dut, "s_axis", clk, dtype=fptype_in)
        self.backpressure = BitDriver(self.dut.m_axis_tready, clk)
        if self.latch_type==0:
            self.event = Event()
        else:
            self.event = None
        self.stream_out = AxisSlave(dut, "m_axis", clk, dtype=fptype_out, event=self.event)

        # Reconstruct the input transactions from the pins
        # and send them to our 'model'
        self.stream_in_recovered = AxisSlave(dut, "s_axis", clk, callback=self.model, dtype=fptype_in)


        # Create a scoreboard on the stream_out bus
        self.pkts_sent = 0
        self.expected_output = []
        self.scoreboard = Scoreboard(dut)
        self.scoreboard.add_interface(self.stream_out, self.expected_output, strict_type=True)

        # Set verbosity on our various interfaces
        level = logging.DEBUG if debug else logging.WARNING
        self.stream_in.log.setLevel(level)
        self.stream_in_recovered.log.setLevel(level)

    def model(self, transaction):
        """Model the DUT based on the input transaction"""
        self.dut._log.info("Sent a packet of %d words" % len(transaction))
        #trans = [FXnum(float(x),self.stream_out.dtype) for x in transaction]
        trans = transaction
        self.expected_output.append(trans)
        self.pkts_sent += 1
        if self.event is not None:
            self.event.set()
            self.event.clear()

    @cocotb.coroutine
    def reset(self):
        self.dut._log.debug("Resetting DUT")
        self.aresetn <= 0
        self.stream_in.bus.tvalid <= 0
        self.stream_in.bus.tlast <= 0
        self.stream_in.bus.tdata <= 0
        self.stream_out.bus.tready <= 0
        yield RisingEdge(self.aclk)
        yield RisingEdge(self.aclk)
        yield RisingEdge(self.aclk)
        self.aresetn <= 1
        self.stream_out.bus.tready <= 1
        self.dut._log.debug("Out of reset")


@cocotb.coroutine
def run_test(dut, data_in=None, idle_inserter=None,
             backpressure_inserter=None, pipeline=10):
    clk = dut.aclk
    cocotb.fork(Clock(clk, 5000, 'ps').start())
    tb = EndianSwapperTB(dut, clk, dut.aresetn, pipeline)

    yield tb.reset()

    # Start off any optional coroutines
    if idle_inserter is not None:
        tb.stream_in.set_valid_generator(idle_inserter())
    if backpressure_inserter is not None:
        tb.backpressure.start(backpressure_inserter())

    npkts = 0
    # Send in the packets
    for transaction in data_in():
        yield tb.stream_in.send(transaction)
        npkts += 1

    # Drop input tvalid
    dut.s_axis_tvalid <= 0
    dut.s_axis_tlast <= 0

    # extra clocks to push thru pipline
    for x in range(pipeline):
        yield RisingEdge(clk)

    if npkts != tb.pkts_sent:
        raise TestFailure("Testbench Driver queued %d packets to the DUT, but DUT accepted only %d" % (
                          npkts, tb.pkts_sent))
    else:
        dut._log.info("DUT correctly counted %d packets" % tb.pkts_sent)

    raise tb.scoreboard.result
'''
def random_float(lower=-1.0, upper=1.0):
    while True:
        yield np.random.uniform(lower,upper)

def random_int(lower=0, upper=256):
    return random.randrange(lower,upper))
'''
def random_floats(num, lower=-1.0, upper=1.0):
    return [np.random.uniform(lower,upper) for _ in range(num)]

def random_ints(num, lower=0, upper=9):
    return [random.randrange(lower,upper) for _ in range(num)]

def random_packet_sizes(data_generator=None, config_gen=None):
    """random string data of a random length"""
    for i in range(5):
        pkt_size = random.randint(20, 20)
        yield [ 1,2,3,4,5,6,7,8,9,10 ]
        #yield random_floats(pkt_size, -1.0, 1.0)


factory = TestFactory(run_test)
factory.add_option("data_in",
                   [random_packet_sizes])
factory.add_option("idle_inserter",
                   [None, wave, intermittent_single_cycles, random_50_percent])
factory.add_option("backpressure_inserter",
                   [None, wave, intermittent_single_cycles, random_50_percent])
factory.generate_tests("A_")

