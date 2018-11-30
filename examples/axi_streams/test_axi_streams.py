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

import logging
import cocotb

from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Event
from cocotb.drivers import BitDriver
from cocotb.drivers.ambastream import AxisMaster
from cocotb.monitors.ambastream import AxisSlave
from cocotb.regression import TestFactory
from cocotb.scoreboard import Scoreboard
from cocotb.result import TestFailure
from FixedPoint import FXfamily


# Data generators
from cocotb.generators.bit import (wave, intermittent_single_cycles, random_50_percent)
from cocotb.generators.numeric import (random_data_gen, add_gen, sine_data_gen)
from cocotb.generators.numeric import (ramp_packet_gen, data_packet_gen)


class EndianSwapperTB(object):
    def __init__(self, dut, clk, reset, latency, in_type=int, out_type=int, debug=False):
        self.dut = dut
        self.aclk = clk
        self.aresetn = reset

        # Read module parameters from DUT verilog file
        self.axis_tdata_size = int(dut.AXIS_TDATA_WIDTH)
        self.integer_bits = 2
        self.latch_type = dut.REG_TYPE

        # Define AXIS drivers and monitors
        self.m_axis = AxisMaster(dut, "s_axis", clk, dtype=in_type)
        self.backpressure = BitDriver(self.dut.m_axis_tready, clk)

        # Event is needed to delay posting of output data, so it arrives at the scoreboard
        # after the modeled input data.
        if self.latch_type == 0:
            self.event = Event()
        else:
            self.event = None
        self.s_axis = AxisSlave(dut, "m_axis", clk, dtype=out_type, event=self.event)

        # Reconstruct the input transactions from what the DUT accepts
        # and send them to our 'model'
        self.m_axis_sent = AxisSlave(dut, "s_axis", clk, callback=self.model, dtype=in_type)

        # Create a scoreboard on the.s_axis bus
        self.pkts_sent = 0
        self.expected_output = []
        self.scoreboard = Scoreboard(dut)
        self.scoreboard.add_interface(self.s_axis, self.expected_output, strict_type=True)

        # Set verbosity on our various interfaces
        level = logging.DEBUG if debug else logging.WARNING
        self.m_axis.log.setLevel(level)
        self.m_axis_sent.log.setLevel(level)

    def model(self, transaction):
        """Model the DUT based on the input transaction"""
        self.dut._log.info("Sent a packet of %d words" % len(transaction))
        # trans = [FXnum(float(x),self.s_axis.dtype) for x in transaction]
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
        self.m_axis.bus.tvalid <= 0
        self.m_axis.bus.tlast <= 0
        self.m_axis.bus.tdata <= 0
        self.s_axis.bus.tready <= 0
        yield RisingEdge(self.aclk)
        yield RisingEdge(self.aclk)
        yield RisingEdge(self.aclk)
        self.aresetn <= 1
        self.s_axis.bus.tready <= 1
        self.dut._log.debug("Out of reset")


@cocotb.coroutine
def run_test(dut, data_config=None, idle_inserter=None,
             backpressure_inserter=None, pipeline=10):

    clk = dut.aclk
    cocotb.fork(Clock(clk, 5000, 'ps').start())

    # Read module parameters from DUT verilog file
    tdata_size = int(dut.AXIS_TDATA_WIDTH)
    integer_bits = 1

    if data_config['dtype'] == float:
        # Define data types
        type_in = FXfamily(tdata_size - integer_bits, integer_bits)
        type_out = FXfamily(tdata_size - integer_bits, integer_bits)
    else:
        type_in = int
        type_out = int

    tb = EndianSwapperTB(dut, clk, dut.aresetn, pipeline, type_in, type_out)

    yield tb.reset()

    # Start off any optional coroutines
    if idle_inserter is not None:
        tb.m_axis.set_valid_generator(idle_inserter())
    if backpressure_inserter is not None:
        tb.backpressure.start(backpressure_inserter())

    npkts = 0
    # Send in the packets
    for transaction in data_config['packet_generator'](data_config):
        yield tb.m_axis.send(transaction)
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


config_ramp = {'packet_generator': ramp_packet_gen,
              'lower': 0,
              'upper': 128,
              'packet_size': 128,
              'n_packets': 6,
              'dtype': int}

config_rand= {'packet_generator': data_packet_gen,
              'data_generator': random_data_gen,
              'lower': -128,
              'upper': 128,
              'packet_size': 1024,
              'n_packets': 4,
              'dtype': int}

config_sin = {'packet_generator': data_packet_gen,
              'data_generator': sine_data_gen,
              'lower': -1.0,
              'upper': 0.99999,
              'packet_size': 1024,
              'n_packets': 4,
              'dt': 8e-9,
              'freq': 488281.25,
              'dtype': float}

factory1 = TestFactory(run_test)
factory1.add_option("data_config", [config_ramp, config_rand, config_sin])
factory1.add_option("idle_inserter", [None, wave, intermittent_single_cycles, random_50_percent])
factory1.add_option("backpressure_inserter", [None, wave, intermittent_single_cycles, random_50_percent])
factory1.generate_tests("Idle & Backpressure Tests_")

config_noise  = {'data_generator': random_data_gen,
                 'lower': -0.5,
                 'upper': 0.5,
                 'dtype': float}

config_signal = { 'data_generator': sine_data_gen,
                  'lower': -0.5,
                  'upper': 0.5,
                  'dt': 8e-9,
                  'freq': 488281.25,
                  'dtype': float}

config_add = {'packet_generator': data_packet_gen,
              'data_generator': add_gen,
              'sub_configs': [config_noise, config_signal],
              'packet_size': 1024,
              'n_packets': 4,
              'dtype': float}

factory2 = TestFactory(run_test)
factory2.add_option("data_config", [config_add])
factory2.generate_tests("Signal Test_")
