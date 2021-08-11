#!/usr/bin/env python


import sys
import os
from setuptools import setup, find_packages


py_version = sys.version_info[:2]


# Ensure supported python version
if py_version < (3, 0):
    raise RuntimeError('pycons3rt3 does not support Python2, for python2 please use pycons3rt and/or pycons3rtapi')


here = os.path.abspath(os.path.dirname(__file__))


# Get the version
version_txt = os.path.join(here, 'pycons3rt3/VERSION.txt')
pycons3rt_version = open(version_txt).read().strip()


# Get the requirements
requirements_txt = os.path.join(here, 'cfg/requirements.txt')
requirements = []
with open(requirements_txt) as f:
    for line in f:
        requirements.append(line.strip())


dist = setup(
    name='pycons3rt3',
    version=pycons3rt_version,
    description='A python3 library for CONS3RT assets and API calls',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Joe Yennaco',
    author_email='joe.yennaco@jackpinetech.com',
    url='https://github.com/cons3rt/pycons3rt3',
    include_package_data=True,
    license='GNU GPL v3',
    packages=find_packages(),
    zip_safe=True,
    install_requires=requirements,
    entry_points={
        'console_scripts': [
            'asset = pycons3rt3.asset:main',
            'cons3rt = pycons3rt3.cons3rt:main',
            's3organizer = pycons3rt3.s3organizer:main',
            'deployment = pycons3rt3.deployment:main',
            'pycons3rt_setup = pycons3rt3.osutil:main',
            'ractl = pycons3rt3.remoteaccesscontoller:main',
            'slack = pycons3rt3.slack:main'
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent'
    ]
)
