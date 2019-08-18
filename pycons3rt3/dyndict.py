#!/usr/bin/python

"""Module: dyndict

This module ingests data into a CONS3RT instance
"""


__author__ = 'Joe Yennaco'


class DynDict(dict):
    """Defines a special dict for dynamic data
    """
    def __getitem__(self, key):
        val = dict.__getitem__(self, key)
        return callable(val) and val(self) or val


def getdict(source):
    """Returns a standard python Dict with computed values
    from the DynDict
    :param source: (DynDict) input
    :return: (dict) Containing computed values
    """
    std_dict = {}
    for var, val in source.items():
        std_dict[var] = source[var]
    return std_dict
