import numpy as np
import random
from cocotb.generators import sine_wave

def random_data_gen(config):
    '''Generates a random data point  (lower, upper]'''
    lower = config['lower']
    upper = config['upper']
    dtype = config['dtype']
    case = {float: np.random.uniform,
            int: random.randrange}
    while True:
        yield case[dtype](lower, upper)


def sine_data_gen(config):
    lower = config['lower']
    upper = config['upper']
    dtype = config['dtype']
    amp = (upper - lower)/2.0
    off = (upper + lower)/2.0
    dt = config.get('dt',1.0)
    freq = config['freq']
    w = 1/freq/dt
    gen = sine_wave(amp,w,off)
    while True:
        yield dtype(next(gen))


def ramp_packet_gen(config):
    '''Generates a series of ramp packets given a data and config generator
       config = {'lower': 0,               Start of ramp
                 'upper': 16,              End of ramp   (lower, upper]
                 'packet_size': 16,        Size of ramp
                 'n_packets': 6,           Number of ramps to generate
                 'dtype': int}             Supports int or float
    '''
    n_packets = config['n_packets']
    for _ in range(n_packets):
        lower = config['lower']
        upper = config['upper']
        pts = config['packet_size']
        yield np.linspace(lower, upper, pts, False, dtype=config['dtype']).tolist()


def add_gen(config):
    """
    Generator for numerically combining multiple generators together
    Args:
        generators (iterable): Generators to combine together
    """
    total = 0.0
    gens = list()
    # initalize generators
    for con in config['sub_configs']:
        gens.append(con['data_generator'](con))
    # loop to generate summed output
    while True:
        for gen in gens:
            total += next(gen)
        yield config['dtype'](total)
        total = 0.0

def data_packet_gen(config):
    '''Generates a packet of data given a data generator and a config generator
       config = {'data_generator':         data generator for points in packet
                 'lower': 0,               lower bound of data generated
                 'upper': 16,              upper bound of data generated (lower, upper]
                 'packet_size': 16,        Number of points in packet
                 'n_packets': 6,           Number of packets to generate
                 'dtype': int}             Supports int or float
    '''
    packet_size = config['packet_size']
    n_packets = config['n_packets']
    data_gen = config['data_generator'](config)
    for _ in range(n_packets):
        yield [next(data_gen) for _ in range(packet_size)]
