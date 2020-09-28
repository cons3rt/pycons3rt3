#!/usr/bin/python

"""Module: logify

This module provides common logging for CONS3RT deployments using
python install scripts, as well as for python modules in the
pycons3rt project in cons3rt-deploying-cons3rt.

Classes:
    Logify: Provides a common logging object and stream that can be
        referenced by other python modules in the pycons3rt project
        as well as other CONS3RT install scripts using python.
"""
import logging
import os
from logging.config import fileConfig

from .osutil import get_pycons3rt_log_dir, get_pycons3rt_conf_dir, initialize_pycons3rt_dirs

__author__ = 'Joe Yennaco'


class Logify(object):
    """Utility to provided common logging across CONS3RT python assets

    This class provides common logging for CONS3RT deployments using
    python install scripts, as well as for python modules in the
    pycons3rt project in cons3rt-deploying-cons3rt.
    """
    # Set up the global pycons3rt logger
    log_dir = get_pycons3rt_log_dir()
    conf_dir = get_pycons3rt_conf_dir()
    log_files = True
    try:
        initialize_pycons3rt_dirs()
    except OSError as ex:
        print('WARNING: Unable to create pycons3rt directories\n{e}'.format(e=str(ex)))
        log_files = False
    config_file = os.path.join(conf_dir, 'pycons3rt-logging.conf')
    log_file_info = os.path.join(log_dir, 'pycons3rt-info.log')
    log_file_debug = os.path.join(log_dir, 'pycons3rt-debug.log')
    log_file_warn = os.path.join(log_dir, 'pycons3rt-warn.log')
    try:
        fileConfig(config_file)
    except (IOError, OSError, Exception):
        _logger = logging.getLogger('pycons3rt3')
        _logger.setLevel(logging.DEBUG)
        _formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s - %(message)s')
        _formatter_threads = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s <%(threadName)s> - %(message)s')
        _stream = logging.StreamHandler()
        _stream.setLevel(logging.INFO)
        _stream.setFormatter(_formatter)
        _logger.addHandler(_stream)
        if log_files:
            _file_info = logging.FileHandler(filename=log_file_info, mode='a')
            _file_info.setLevel(logging.INFO)
            _file_info.setFormatter(_formatter)
            _file_debug = logging.FileHandler(filename=log_file_debug, mode='a')
            _file_debug.setLevel(logging.DEBUG)
            _file_debug.setFormatter(_formatter_threads)
            _file_warn = logging.FileHandler(filename=log_file_warn, mode='a')
            _file_warn.setLevel(logging.WARN)
            _file_warn.setFormatter(_formatter_threads)
            _logger.addHandler(_file_info)
            _logger.addHandler(_file_debug)
            _logger.addHandler(_file_warn)
    else:
        _logger = logging.getLogger('pycons3rt3')

    # Set up logger name for this module
    mod_logger = _logger.name + '.logify'
    cls_logger = mod_logger + '.Logify'

    @classmethod
    def __init__(cls):
        pass

    @classmethod
    def __str__(cls):
        return cls._logger.name

    @classmethod
    def set_log_level(cls, log_level):
        """Sets the log level for cons3rt assets

        This method sets the logging level for cons3rt assets using
        pycons3rt. The loglevel is read in from a deployment property
        called loglevel and set appropriately.

        :type log_level: str
        :return: True if log level was set, False otherwise.
        """
        log = logging.getLogger(cls.cls_logger + '.set_log_level')
        if log_level is None:
            log.info('Arg loglevel was None, log level will not be updated.')
            return False
        if not isinstance(log_level, str):
            log.error('Passed arg loglevel must be a string')
            return False
        log_level = log_level.upper()
        if log_level == 'DEBUG':
            cls._logger.setLevel(logging.DEBUG)
        elif log_level == 'INFO':
            cls._logger.setLevel(logging.INFO)
        elif log_level == 'WARN':
            cls._logger.setLevel(logging.WARN)
        elif log_level == 'WARNING':
            cls._logger.setLevel(logging.WARN)
        elif log_level == 'ERROR':
            cls._logger.setLevel(logging.ERROR)
        else:
            log.error('Could not set log level, this is not a valid log level: %s', log_level)
            return False
        log.info('pycons3rt loglevel set to: {s}'.format(s=log_level))
        return True

    @classmethod
    def get_name(cls):
        """
        :return: (str) Name of the class-level logger
        """
        return cls._logger.name


def main():
    """Sample usage for this python module

    This main method simply illustrates sample usage for this python
    module.

    :return: None
    """
    log = logging.getLogger(Logify.get_name() + '.logify.main')
    log.info('logger name is: %s', Logify.get_name())
    log.debug('This is DEBUG')
    log.info('This is INFO')
    log.warning('This is a WARNING')
    log.error('This is an ERROR')


if __name__ == '__main__':
    main()
