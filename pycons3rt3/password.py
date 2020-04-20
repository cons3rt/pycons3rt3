#!/usr/bin/env python3

"""Module: password

This module generates a random password

"""
import logging
import random
import string

from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.password'


def generate_random_password(password_length=17, num_spec=2, num_digits=2):
    """Returns a random password meeting the following requirements:

    :param password_length: (int) length of the random password
    :param num_spec: (int) number of special characters
    :param num_digits: (int) number of digits
    :return: String password or None
    """
    log = logging.getLogger(mod_logger + '.generate_random_password')

    # Validate the inputs
    if num_spec + num_digits > password_length:
        log.error('Unable to generate password of length {n} with the args provided'.format(n=str(password_length)))
        return

    log.info('Generating password of length {t} with: {s} specials and {d} digits'.format(
        t=str(password_length), s=str(num_spec), d=str(num_digits)))
    special_chars = '#$%&*@'
    pre_password = []
    for _ in range(num_spec):
        pre_password.append(random.SystemRandom().choice(special_chars))
    for _ in range(num_digits):
        pre_password.append(random.SystemRandom().choice(string.digits))
    bulk = password_length - num_digits - num_spec
    for _ in range(bulk):
        pre_password.append(random.SystemRandom().choice(string.ascii_lowercase + string.ascii_uppercase))
    password = []
    for i in range(len(pre_password)):
        pick = random.choice(pre_password)
        pre_password.remove(pick)
        password.append(pick)
    password = ''.join(password)
    return password
