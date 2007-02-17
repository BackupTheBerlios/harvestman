# -- coding: latin-1
""" singleton.py - Singleton design-pattern implemented using
    meta-classes. This module is part of HarvestMan program.

    Author: Anand B Pillai <abpillai at gmail dot com>

    Created Anand B Pillai Feb 2 2007
    

Copyright(C) 2007 Anand B Pillai.
"""

__version__ = '1.5 b1'
__author__ = 'Anand B Pillai'

class SingletonMeta(type):
    """ A type for Singleton classes """

    def my_new(cls,name,bases=(),dct={}):
        if not cls.instance:
            cls.instance = object.__new__(cls)
        return cls.instance
    
    def __init__(cls, name, bases, dct):
        super(SingletonMeta, cls).__init__(name, bases, dct)
        cls.instance = None
        cls.__new__ = cls.my_new

class Singleton(object):
    """ The default implementation for a Python Singleton class """

    __metaclass__ = SingletonMeta

    def getInstance(cls, *args):
        if not cls.instance:
            cls(*args)
        return cls.instance

    getInstance = classmethod(getInstance)
