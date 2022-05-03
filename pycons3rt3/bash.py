#!/usr/bin/env python3

"""Module: bash

This module provides utilities for running standard bash commands
from python.

"""
import logging
import os
import subprocess
import errno
import fileinput
import re
import sys
import zipfile
import socket
import contextlib
import signal
import time
import platform
import shutil
from datetime import datetime
from threading import Timer

from .logify import Logify
from .exceptions import CommandError, SystemRebootError, SystemRebootTimeoutError
from .network import validate_ip_address as network_validate_ip_address

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.bash'


def process_killer(p):
    """Returns a function to kill the process p
    :param p: Process
    :return: kill function for process p
    """
    return p.kill()


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


def run_command(command, timeout_sec=3600.0, output=True, bufsize=-1, print_output=True):
    """Runs a command using the subprocess module

    :param command: List containing the command and all args
    :param timeout_sec: (float) seconds to wait before killing
        the command.
    :param output: (bool) True collects output, False ignores output
    :param bufsize: (int) See python3 subprocess docs
    :param print_output: (bool) Set True to print command output, False to not print
    :return: Dict containing the command output and return code
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.run_command')
    if not isinstance(command, list):
        raise CommandError('command arg must be a list')
    if output:
        subproc_stdout = subprocess.PIPE
        subproc_stderr = subprocess.STDOUT
    else:
        subproc_stdout = None
        subproc_stderr = None
    command_str = ' '.join(command)
    timer = None
    log.debug('Running command: {c}'.format(c=command_str))
    output_collector = ''
    try:
        log.debug('Opening subprocess...')
        subproc = subprocess.Popen(
            command,
            bufsize=bufsize,
            stdin=subprocess.DEVNULL,
            stdout=subproc_stdout,
            stderr=subproc_stderr)
        log.debug('Opened subprocess wih PID: {p}'.format(p=subproc.pid))
        log.debug('Setting up process kill timer for PID {p} at {s} sec...'.format(p=subproc.pid, s=timeout_sec))
        kill_proc = process_killer
        timer = Timer(timeout_sec, kill_proc, [subproc])
        timer.start()
        if output:
            log.debug('Collecting and logging output...')
            with subproc.stdout:
                for line in iter(subproc.stdout.readline, b''):
                    line_str = line.decode('utf-8')
                    line_str = str(line_str).rstrip()
                    output_collector += line_str + '\n'
                    if print_output:
                        print(">>> " + line_str)
        log.debug('Waiting for process completion...')
        subproc.wait()
        log.debug('Collecting the exit code...')
        code = subproc.poll()
    except ValueError as exc:
        raise CommandError('Bad command supplied: {c}'.format(c=command_str)) from exc
    except (OSError, IOError) as exc:
        raise CommandError('There was a problem running command: {c}'.format(c=command_str)) from exc
    except subprocess.CalledProcessError as exc:
        raise CommandError('Command returned a non-zero exit code: {c}, return code'.format(c=command_str)) from exc
    finally:
        if timer is not None:
            log.debug('Cancelling the timer...')
            timer.cancel()
        else:
            log.debug('No need to cancel the timer.')
    # Collect exit code and output for return
    output = output_collector.strip()
    try:
        code = int(code)
    except ValueError as exc:
        raise CommandError('Return code {c} could not be parsed into an int'.format(c=code)) from exc
    else:
        log.debug('Command executed and returned code: {c} with output:\n{o}'.format(c=code, o=output))
        output = {
            'output': output,
            'code': code
        }
    return output


def run_command_large_buffer(command, timeout_sec=3600.0):
    """Runs a command using the subprocess module

    :param command: List containing the command and all args
    :param timeout_sec (float) seconds to wait before killing
        the command.
    :return: Dict containing stdout, stderr, and return code
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.run_command')
    if not isinstance(command, list):
        raise CommandError('command arg must be a list')
    command_str = ' '.join(command)
    log.debug('Running command: {c}'.format(c=command_str))
    subproc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pid = subproc.pid
    log.debug('Opened up PID {p} with a timeout of {s} sec...'.format(p=pid, s=str(timeout_sec)))
    timeout = False
    try:
        stdout, stderr = subproc.communicate(timeout=timeout_sec)
    except ValueError as exc:
        raise CommandError('Bad command supplied: {c}'.format(c=command_str)) from exc
    except (OSError, IOError) as exc:
        raise CommandError('There was a problem running command: {c}'.format(c=command_str)) from exc
    except subprocess.CalledProcessError as exc:
        raise CommandError('Command returned a non-zero exit code: {c}, return code'.format(c=command_str)) from exc
    except subprocess.TimeoutExpired:
        log.error('Command timeout of {t} seconds expired for: [{c}]'.format(t=str(timeout_sec), c=command_str))
        timeout = True

    if timeout:
        log.info('Attempting to kill the PID: {p}'.format(p=str(pid)))
        try:
            subproc.terminate()
            subproc.kill()
            os.kill(pid, signal.SIGINT)
            log.error('Force terminated: {p}'.format(p=str(pid)))
        except OSError as exc:
            log.info('Process {p} exited gracefully\n{e}'.format(p=str(pid), e=str(exc)))
        except subprocess.TimeoutExpired:
            raise CommandError('Command timed out and could not retrieve output for: {c}'.format(c=command_str))
        finally:
            raise CommandError('Command timed out: {c}'.format(c=command_str))

    # Collect exit code and output for return
    code = subproc.poll()
    stdout = stdout.decode('utf-8')
    stderr = stderr.decode('utf-8')
    output = {
        'stdout': stdout,
        'stderr': stderr,
        'code': code
    }
    return output


def validate_ip_address(ip_address):
    """Deprecated, but left here for backwards compatibility

    :param ip_address:
    :return:
    """
    return network_validate_ip_address(ip_address=ip_address)


def ip_addr():
    """Uses the ip addr command to enumerate IP addresses by device

    :return: (dict) Containing device: ip_address
    """
    log = logging.getLogger(mod_logger + '.ip_addr')
    log.debug('Running the ip addr command...')
    ip_addr_output = {}

    command = ['ip', 'addr']
    try:
        ip_addr_result = run_command(command, timeout_sec=20, output=True, print_output=False)
    except CommandError as exc:
        raise CommandError('There was a problem running command: {c}'.format(c=' '.join(command))) from exc

    ip_addr_lines = ip_addr_result['output'].split('\n')

    for line in ip_addr_lines:
        line = line.strip()
        if line.startswith('inet6'):
            continue
        elif line.startswith('inet'):
            parts = line.split()
            try:
                ip_address = parts[1].strip().split('/')[0]
            except KeyError:
                continue
            else:
                if not validate_ip_address(ip_address):
                    continue
                else:
                    for part in parts:
                        part = part.strip()
                        if part.strip().startswith('eth') or part.strip().startswith('eno') or \
                                part.strip().startswith('ens'):
                            device = part
                            ip_addr_output[device] = ip_address
    return ip_addr_output


def get_mac_addresses():
    """Uses the ip addr command to enumerate mac addresses by device

    :return: (dict) Containing device: ip_address
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.get_mac_addresses')
    log.debug('Running the ip addr command...')
    mac_addresses = {}

    command = ['ip', 'addr']
    try:
        ip_addr_result = run_command(command, timeout_sec=20, output=True, print_output=False)
    except CommandError as exc:
        raise CommandError('There was a problem running command: {c}'.format(c=' '.join(command))) from exc

    ip_addr_lines = ip_addr_result['output'].split('\n')
    mac_address = None
    device = None
    for line in ip_addr_lines:
        line = line.strip()
        if line.startswith('link/ether'):
            parts = line.split()
            mac_address = parts[1]
        elif line.startswith('inet'):
            if not mac_address:
                continue
            parts = line.split()
            device = parts[-1]
        if device and mac_address:
            mac_addresses[device] = mac_address
            log.info('Found device [{d}] with mac address: [{m}]'.format(d=device, m=mac_address))
            device = None
            mac_address = None
    return mac_addresses


def get_ip_addresses():
    """Gets the ip addresses from ifconfig

    :return: (dict) of devices and aliases with the IPv4 address
    """
    log = logging.getLogger(mod_logger + '.get_ip_addresses')

    command = ['/sbin/ifconfig']
    try:
        result = run_command(command, output=True, print_output=False)
    except CommandError as exc:
        raise CommandError('There was a problem running ifconfig') from exc
    ifconfig = result['output'].strip()

    # Scan the ifconfig output for IPv4 addresses
    devices = {}
    parts = ifconfig.split()
    device = None
    for part in parts:

        if device is None:
            if 'eth' in part or 'eno' in part:
                device = part
        else:
            test = part.split(':', 1)
            if len(test) == 2:
                if test[0] == 'addr':
                    ip_address = test[1]
                    log.info('Found IP address %s on device %s', ip_address,
                             device)
                    devices[device] = ip_address
                    device = None
    return devices


def get_mac_address(device_index=0):
    """Returns the Mac Address given a device index

    :param device_index: (int) Device index
    :return: (str) Mac address or None
    """
    log = logging.getLogger(mod_logger + '.get_mac_address')
    command = ['ip', 'addr', 'show', 'eth{d}'.format(d=device_index)]
    log.info('Attempting to find a mac address at device index: {d}'.format(d=device_index))
    try:
        result = run_command(command)
    except CommandError as exc:
        log.error('There was a problem running command, unable to determine mac address: {c}\n{e}'.format(
                c=command, e=str(exc)))
        return
    ipaddr = result['output'].split()
    get_next = False
    mac_address = None
    for part in ipaddr:
        if get_next:
            mac_address = part
            log.info('Found mac address: {m}'.format(m=mac_address))
            break
        if 'link' in part:
            get_next = True
    if not mac_address:
        log.info('mac address not found for device: {d}'.format(d=device_index))
    return mac_address


def chmod(path, mode, recursive=False):
    """Emulates bash chmod command

    This method sets the file permissions to the specified mode.

    :param path: (str) Full path to the file or directory
    :param mode: (str) Mode to be set (e.g. 0755)
    :param recursive: (bool) Set True to make a recursive call
    :return: int exit code of the chmod command
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.chmod')

    # Validate args
    if not isinstance(path, str):
        msg = 'path argument is not a string'
        log.error(msg)
        raise CommandError(msg)
    if not isinstance(mode, str):
        msg = 'mode argument is not a string'
        log.error(msg)
        raise CommandError(msg)

    # Ensure the item exists
    if not os.path.exists(path):
        msg = 'Item not found: {p}'.format(p=path)
        log.error(msg)
        raise CommandError(msg)

    # Create the chmod command
    command = ['chmod']
    # Make it recursive if specified
    if recursive:
        command.append('-R')
    command.append(mode)
    command.append(path)
    try:
        result = run_command(command)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    log.info('chmod command exited with code: {c}'.format(c=result['code']))
    return result['code']


def mkdir_p(path):
    """Emulates 'mkdir -p' in bash

    :param path: (str) Path to create
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.mkdir_p')
    if not isinstance(path, str):
        msg = 'path argument is not a string'
        log.error(msg)
        raise CommandError(msg)
    log.info('Attempting to create directory: %s', path)
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            msg = 'Unable to create directory: {p}'.format(p=path)
            log.error(msg)
            raise CommandError(msg)


def source(script):
    """Emulates 'source' command in bash, updates os.environ with
    environment variables

    :param script: (str) Full path to the script to source
    :return: (dict) Updated environment
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.source')
    if not isinstance(script, str):
        raise CommandError('script argument must be a string')
    if not os.path.isfile(script):
        raise CommandError('File not found: {f}'.format(f=script))
    log.debug('Attempting to source script: {f}'.format(f=script))
    command = ['bash', '-c', '. {s}; env;'.format(s=script)]
    try:
        result = run_command(command, timeout_sec=10.0, output=True, print_output=False)
    except CommandError as exc:
        raise CommandError('Problem sourcing script: {s}'.format(s=script)) from exc
    env = {}
    if result['output'] == '':
        log.debug('No environment variable found to update in script: {s}'.format(s=script))
        return
    env_vars = result['output'].split('\n')
    for env_var in env_vars:
        entry = env_var.split("=", 1)
        if len(entry) != 2:
            log.warning('Not in prop=value format, skipping: {p}'.format(p=env_var))
            continue
        try:
            env[entry[0]] = entry[1]
        except IndexError as exc:
            log.warning('Problem setting environment variable, skipping: {p}\n{e}'.format(p=env_var, e=str(exc)))
            continue
        log.debug('Added environment variable {p}={v}'.format(p=entry[0], v=entry[1]))
    try:
        os.environ.update(env)
    except OSError as exc:
        msg = 'Problem updating the environment'
        raise CommandError(msg) from exc
    return env


def source_env():
    """Sources environment variable files

    :return: None
    """
    log = logging.getLogger(mod_logger + '.source_env')
    etc_bashrc = '/etc/bashrc'
    etc_profile = '/etc/profile'
    bash_profile = os.path.join(os.path.expanduser('~'), '.bash_profile')
    try:
        if os.path.isfile(etc_bashrc):
            source(etc_bashrc)
        if os.path.isfile(etc_profile):
            source(etc_profile)
        if os.path.isfile(bash_profile):
            source(bash_profile)
    except CommandError as exc:
        log.warning('Problem sourcing environment files\n{e}'.format(e=str(exc)))


def yum_update(downloadonly=False, dest_dir='/tmp'):
    """Run a yum update on this system

    This public method runs the yum -y update command to update
    packages from yum. If downloadonly is set to true, the yum
    updates will be downloaded to the specified dest_dir.

    :param dest_dir: (str) Full path to the download directory
    :param downloadonly: Boolean
    :return: int exit code from the yum command
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.yum_update')

    # Type checks on the args
    if not isinstance(dest_dir, str):
        raise CommandError('dest_dir argument must be a string')
    if not isinstance(downloadonly, bool):
        raise CommandError('downloadonly argument must be a bool')

    # If downloadonly was True, download packages to dest_dir
    if downloadonly:
        # Create the destination directory if it does not exist
        log.info('Creating directory: %s', dest_dir)
        try:
            mkdir_p(dest_dir)
        except OSError as exc:
            raise CommandError('Unable to create destination directory: {d}'.format(d=dest_dir)) from exc

        # Build command string with downloadonly options specified
        command = ['yum', '-y', 'update', '--downloadonly',
                   '--downloaddir={d}'.format(d=dest_dir)]
        log.info('Downloading updates from yum to %s...', dest_dir)
    else:
        # Build command string to update directly
        command = ['yum', '-y', 'update']
        log.info('Installing yum updates from RHN...')

    # Run the command
    try:
        result = run_command(command)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    log.info('Yum update completed and exit with code: {c}'.format(
        c=result['code']))
    return result['code']


def yum_install(packages, downloadonly=False, dest_dir='/tmp'):
    """Installs (or downloads) a list of packages from yum

    This public method installs a list of packages from yum or
    downloads the packages to the specified destination directory using
    the yum-downloadonly yum plugin.

    :param downloadonly: Boolean, set to only download the package and
        not install it
    :param packages: List of package names (str) to download param
    :param dest_dir: (str) Full path to the download directory
    :return: int exit code from the yum command
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.yum_install')

    # Type checks on the args
    if not isinstance(dest_dir, str):
        msg = 'dest_dir argument must be a string'
        log.error(msg)
        raise CommandError(msg)
    if not isinstance(packages, list):
        msg = 'packages argument must be a list'
        log.error(msg)
        raise CommandError(msg)
    if not isinstance(downloadonly, bool):
        msg = 'downloadonly argument must be a bool'
        log.error(msg)
        raise CommandError(msg)
    if not packages:
        msg = 'Empty list of packages provided'
        log.error(msg)
        raise CommandError(msg)
    for package in packages:
        # Ensure the package is specified as a string
        if not isinstance(package, str):
            msg = 'One of the packages was not specified as a string'
            log.error(msg)
            raise CommandError(msg)

    # Build the yum install command string
    command = ['yum', '-y', 'install'] + packages

    # If downloadonly was True, download packages to dest_dir
    if downloadonly:
        log.info('yum downloadonly was specified, adding additional options...')

        # Append downloadonly args to the command
        command += ['--downloadonly', '--downloaddir={d}'.format(d=dest_dir)]

        # Create the destination directory if it does not exist
        log.info('Creating directory: %s', dest_dir)
        try:
            mkdir_p(dest_dir)
        except CommandError as exc:
            raise CommandError('Unable to create destination directory: {d}'.format(d=dest_dir)) from exc
        log.info('Downloading packages from yum to %s...', dest_dir)
    else:
        log.info('Installing yum packages from RHN...')

    # Run the yum install command
    try:
        result = run_command(command)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    log.info('Yum update completed and exit with code: {c}'.format(
        c=result['code']))
    return result['code']


def rpm_install(install_dir):
    """This method installs all RPM files in a specific dir

    :param install_dir: (str) Full path to the directory
    :return int exit code form the rpm command
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.rpm_install')

    # Type checks on the args
    if not isinstance(install_dir, str):
        raise CommandError('install_dir argument must be a string')

    # Ensure the install_dir directory exists
    if not os.path.isdir(install_dir):
        raise CommandError('Directory not found: {f}'.format(f=install_dir))

    # Create the command
    command = ['rpm', '-iv', '--force', '{d}/*.rpm'.format(d=install_dir)]

    # Run the rpm command
    try:
        result = run_command(command)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    log.info('RPM completed and exit with code: {c}'.format(c=result['code']))
    return result['code']


def sed(file_path, pattern, replace_str, g=0):
    """Python impl of the bash sed command

    This method emulates the functionality of a bash sed command.

    :param file_path: (str) Full path to the file to be edited
    :param pattern: (str) Search pattern to replace as a regex
    :param replace_str: (str) String to replace the pattern
    :param g: (int) Whether to globally replace (0) or replace 1
        instance (equivalent to the 'g' option in bash sed
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.sed')

    # Type checks on the args
    if not isinstance(file_path, str):
        msg = 'file_path argument must be a string'
        log.error(msg)
        raise CommandError(msg)
    if not isinstance(pattern, str):
        msg = 'pattern argument must be a string'
        log.error(msg)
        raise CommandError(msg)
    if not isinstance(replace_str, str):
        msg = 'replace_str argument must be a string'
        log.error(msg)
        raise CommandError(msg)

    # Ensure the file_path file exists
    if not os.path.isfile(file_path):
        msg = 'File not found: {f}'.format(f=file_path)
        log.error(msg)
        raise CommandError(msg)

    # Search for a matching pattern and replace matching patterns
    log.info('Updating file: %s...', file_path)
    for line in fileinput.input(file_path, inplace=True):
        if re.search(pattern, line):
            log.info('Updating line: %s', line)
            new_line = re.sub(pattern, replace_str, line, count=g)
            log.info('Replacing with line: %s', new_line)
            sys.stdout.write(new_line)
        else:
            sys.stdout.write(line)


def zip_dir(dir_path, zip_file):
    """Creates a zip file of a directory tree

    This method creates a zip archive using the directory tree dir_path
    and adds to zip_file output.

    :param dir_path: (str) Full path to directory to be zipped
    :param zip_file: (str) Full path to the output zip file
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.zip_dir')

    # Validate args
    if not isinstance(dir_path, str):
        msg = 'dir_path argument must be a string'
        log.error(msg)
        raise CommandError(msg)
    if not isinstance(zip_file, str):
        msg = 'zip_file argument must be a string'
        log.error(msg)
        raise CommandError(msg)

    # Ensure the dir_path file exists
    if not os.path.isdir(dir_path):
        msg = 'Directory not found: {f}'.format(f=dir_path)
        log.error(msg)
        raise CommandError(msg)

    try:
        with contextlib.closing(zipfile.ZipFile(zip_file, 'w', allowZip64=True)) as zip_w:
            for root, dirs, files in os.walk(dir_path):
                for f in files:
                    log.debug('Adding file to zip: %s', f)
                    strip = len(dir_path) - len(os.path.split(dir_path)[-1])
                    file_name = os.path.join(root, f)
                    archive_name = os.path.join(root[strip:], f)
                    zip_w.write(file_name, archive_name)
    except Exception as exc:
        raise CommandError('Unable to create zip file: {f}'.format(f=zip_file)) from exc
    log.info('Successfully created zip file: %s', zip_file)


def update_hosts_file(ip, entry):
    """Updates the /etc/hosts file for the specified ip

    This method updates the /etc/hosts file for the specified IP
    address with the specified entry.

    :param ip: (str) IP address to be added or updated
    :param entry: (str) Hosts file entry to be added
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.update_hosts_file')

    # Validate args
    if not isinstance(ip, str):
        msg = 'ip argument must be a string'
        log.error(msg)
        raise CommandError(msg)
    if not isinstance(entry, str):
        msg = 'entry argument must be a string'
        log.error(msg)
        raise CommandError(msg)

    # Ensure the file_path file exists
    hosts_file = '/etc/hosts'
    if not os.path.isfile(hosts_file):
        msg = 'File not found: {f}'.format(f=hosts_file)
        log.error(msg)
        raise CommandError(msg)

    # Updating /etc/hosts file
    log.info('Updating hosts file: {f} with IP {i} and entry: {e}'.format(f=hosts_file, i=ip, e=entry))
    full_entry = ip + ' ' + entry.strip() + '\n'
    updated = False
    for line in fileinput.input(hosts_file, inplace=True):
        if re.search(ip, line):
            if line.split()[0] == ip:
                log.info('Found IP {i} in line: {li}, updating...'.format(i=ip, li=line))
                log.info('Replacing with new line: {n}'.format(n=full_entry))
                sys.stdout.write(full_entry)
                updated = True
            else:
                log.debug('Found ip {i} in line {li} but not an exact match, adding line back to hosts file {f}...'.
                          format(i=ip, li=line, f=hosts_file))
                sys.stdout.write(line)
        else:
            log.debug('IP address {i} not found in line, adding line back to hosts file {f}: {li}'.format(
                    i=ip, li=line, f=hosts_file))
            sys.stdout.write(line)

    # Append the entry if the hosts file was not updated
    if updated is False:
        with open(hosts_file, 'a') as f:
            log.info('Appending hosts file entry to {f}: {e}'.format(f=hosts_file, e=full_entry))
            f.write(full_entry)


def set_hostname(new_hostname, pretty_hostname=None):
    """Sets this hosts hostname

    This method updates /etc/sysconfig/network and calls the hostname
    command to set a hostname on a Linux system.

    :param new_hostname: (str) New hostname
    :param pretty_hostname: (str) new pretty hostname, set to the same as
        new_hostname if not provided
    :return (int) exit code of the hostname command
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.set_hostname')

    # Ensure the hostname is a str
    if not isinstance(new_hostname, str):
        msg = 'new_hostname argument must be a string'
        raise CommandError(msg)

    # Update the network config file
    network_file = '/etc/sysconfig/network'
    if os.path.isfile(network_file):
        log.info('Updating {f} with the new hostname: {h}...'.format(f=network_file, h=new_hostname))
        try:
            sed(network_file, '^HOSTNAME=.*', 'HOSTNAME=' + new_hostname)
        except CommandError as exc:
            raise CommandError('Unable to update [{f}]'.format(f=network_file)) from exc
    else:
        log.info('Network file not found, will not be updated: {f}'.format(f=network_file))

    # Update the hostname
    if is_systemd():
        hostname_file = '/etc/hostname'
        pretty_hostname_file = '/etc/machine-info'
        log.info('This is systemd, updating files: {h} and {p}'.format(h=hostname_file, p=pretty_hostname_file))

        # Update the hostname file
        log.info('Updating hostname file: {h}...'.format(h=hostname_file))
        if os.path.isfile(hostname_file):
            os.remove(hostname_file)
        with open(hostname_file, 'w') as f:
            f.write(new_hostname)
        log.info('Updating pretty hostname file: {p}'.format(p=pretty_hostname_file))

        # Use the same thing if pretty hostname is not provided
        if pretty_hostname is None:
            log.info('Pretty hostname not provided, using: {p}'.format(p=pretty_hostname))
            pretty_hostname = new_hostname

        # Update the pretty hostname file
        if os.path.isfile(pretty_hostname_file):
            os.remove(pretty_hostname_file)
        with open(pretty_hostname_file, 'w') as f:
            f.write('PRETTY_HOSTNAME={p}'.format(p=pretty_hostname))
        return 0
    else:
        command = ['/bin/hostname', new_hostname]

        # Run the hostname command
        log.info('Running hostname command to set the hostname: [{c}]'.format(c=' '.join(command)))
        try:
            result = run_command(command)
        except CommandError as exc:
            raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
        log.info('Hostname command completed with code: {c} and output:\n{o}'.format(
            c=result['code'], o=result['output']))
        return result['code']


def set_ntp_server(server):
    """Sets the NTP server on Linux

    :param server: (str) NTP server IP or hostname
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.set_ntp_server')

    # Ensure the hostname is a str
    if not isinstance(server, str):
        msg = 'server argument must be a string'
        log.error(msg)
        raise CommandError(msg)
    # Ensure the ntp.conf file exists
    ntp_conf = '/etc/ntp.conf'
    if not os.path.isfile(ntp_conf):
        msg = 'File not found: {f}'.format(f=ntp_conf)
        log.error(msg)
        raise CommandError(msg)
    log.info('Clearing out existing server entries from %s...', ntp_conf)
    try:
        sed(ntp_conf, '^server.*', '', g=0)
    except CommandError as exc:
        raise CommandError('Unable to update file: {f}'.format(f=ntp_conf)) from exc
    out_str = 'server ' + server
    log.info('Appending server: %s', out_str)
    with open(ntp_conf, 'a') as f:
        f.write(out_str)
    log.info('Successfully updated file: {f}'.format(f=ntp_conf))


def copy_ifcfg_file(source_interface, dest_interface):
    """Copies an existing ifcfg network script to another

    :param source_interface: String (e.g. 1)
    :param dest_interface: String (e.g. 0:0)
    :return: None
    :raises TypeError, OSError
    """
    log = logging.getLogger(mod_logger + '.copy_ifcfg_file')
    # Validate args
    if not isinstance(source_interface, str):
        msg = 'source_interface argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(dest_interface, str):
        msg = 'dest_interface argument must be a string'
        log.error(msg)
        raise TypeError(msg)

    network_script = '/etc/sysconfig/network-scripts/ifcfg-eth'
    source_file = network_script + source_interface
    dest_file = network_script + dest_interface
    command = ['cp', '-f', source_file, dest_file]
    try:
        result = run_command(command)
        code = result['code']
    except CommandError as exc:
        raise OSError('Unable to copy the ifcfg file from interface {s} to interface {d}'.format(
            s=source_interface, d=dest_interface)) from exc
    log.info('Copy command exited with code: {c}'.format(c=code))

    if code != 0:
        raise OSError('There was a problem copying file {s} file to {d}'.format(s=source, d=dest_file))

    # Updating the destination network script DEVICE property
    try:
        sed(file_path=dest_file, pattern='^DEVICE=.*',
            replace_str='DEVICE="eth{i}"'.format(i=dest_interface))
    except CommandError as exc:
        raise CommandError('Unable to update DEVICE in file: {d}'.format(d=dest_file)) from exc
    log.info('Successfully created file: {d}'.format(d=dest_file))

    log.info('Restarting networking in 10 seconds to ensure the changes take effect...')
    time.sleep(10)
    retry_time = 10
    max_retries = 10
    for i in range(1, max_retries+2):
        if i > max_retries:
            raise OSError(
                'Unable to successfully start the networking service after {m} attempts'.format(m=max_retries))
        log.info('Attempting to restart the networking service, attempt #{i} of {m}'.format(i=i, m=max_retries))
        try:
            service_network_restart()
        except CommandError as exc:
            log.warning('Attempted unsuccessfully to restart networking on attempt #{i} of {m}, '
                        'trying again in {t} seconds\n{e}'.format(i=i, m=max_retries, t=retry_time, e=str(exc)))
            time.sleep(retry_time)
        else:
            log.info('Successfully restarted networking')
            break
    log.info('Successfully configured interface: {d}'.format(d=dest_interface))


def remove_ifcfg_file(device_index='0'):
    """Removes the ifcfg file at the specified device index
    and restarts the network service

    :param device_index: (int) Device Index
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.remove_ifcfg_file')
    if not isinstance(device_index, str):
        raise CommandError('device_index argument must be a string')
    network_script = '/etc/sysconfig/network-scripts/ifcfg-eth{d}'.format(d=device_index)
    if not os.path.isfile(network_script):
        log.info('File does not exist, nothing will be removed: {n}'.format(n=network_script))
        return

    # Remove the network config script
    log.info('Attempting to remove file: {n}'.format(n=network_script))
    try:
        os.remove(network_script)
    except(IOError, OSError) as exc:
        raise OSError('There was a problem removing network script file: {n}'.format(n=network_script)) from exc
    else:
        log.info('Successfully removed file: {n}'.format(n=network_script))

    # Restart the network service
    log.info('Restarting the network service...')
    try:
        service_network_restart()
    except CommandError as exc:
        raise OSError('There was a problem restarting the network service') from exc
    else:
        log.info('Successfully restarted the network service')


def add_nat_rule(port, source_interface, dest_interface):
    """Adds a NAT rule to iptables

    :param port: String or int port number
    :param source_interface: String (e.g. 1)
    :param dest_interface: String (e.g. 0:0)
    :return: None
    :raises: TypeError, OSError
    """
    log = logging.getLogger(mod_logger + '.add_nat_rule')
    # Validate args
    if not isinstance(source_interface, str):
        msg = 'source_interface argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(dest_interface, str):
        msg = 'dest_interface argument must be a string'
        log.error(msg)
        raise TypeError(msg)

    ip_addresses = ip_addr()
    destination_ip = ip_addresses['eth{i}'.format(i=dest_interface)]
    log.info('Using destination IP address: {d}'.format(d=destination_ip))

    command = ['iptables', '-t', 'nat', '-A', 'PREROUTING', '-i',
               'eth{s}'.format(s=source_interface), '-p', 'tcp',
               '--dport', str(port), '-j', 'DNAT', '--to',
               '{d}:{p}'.format(p=port, d=destination_ip)]
    log.info('Running command: {c}'.format(c=command))
    try:
        subprocess.check_call(command)
    except OSError as exc:
        raise OSError('There was a problem running command: {c}'.format(c=command)) from exc
    except subprocess.CalledProcessError as exc:
        raise OSError('Command returned a non-zero exit code: {c}'.format(c=command)) from exc
    else:
        log.info('Successfully ran command: {c}'.format(c=command))

    # Save the iptables with the new NAT rule
    try:
        save_iptables()
    except OSError as exc:
        raise OSError('OSError: There was a problem saving iptables rules') from exc
    log.info('Successfully saved iptables rules with the NAT rule')


def service_network_restart():
    """Restarts the network service on linux
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.service_network_restart')
    command = ['service', 'network', 'restart']
    time.sleep(5)
    try:
        result = run_command(command)
        time.sleep(5)
        code = result['code']
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    log.info('Network restart produced output:\n{o}'.format(o=result['output']))

    if code != 0:
        msg = 'Network services did not restart cleanly, exited with code: {c}'.format(c=code)
        log.error(msg)
        raise CommandError(msg)
    else:
        log.info('Successfully restarted networking!')


def save_iptables(rules_file='/etc/sysconfig/iptables'):
    """Saves iptables rules to the provided rules file

    :return: None
    :raises OSError
    """
    log = logging.getLogger(mod_logger + '.save_iptables')

    # Run iptables-save to get the output
    command = ['iptables-save']
    log.debug('Running command: iptables-save')
    try:
        iptables_out = run_command(command, timeout_sec=20)
    except CommandError as exc:
        raise OSError('There was a problem running iptables command: {c}'.format(c=' '.join(command))) from exc

    # Error if iptables-save did not exit clean
    if int(iptables_out['code']) != 0:
        raise OSError('Command [{g}] exited with code [{c}] and output:\n{o}'.format(
            g=' '.join(command), c=iptables_out['code'], o=iptables_out['output']))

    # Back up the existing rules file if it exists
    if os.path.isfile(rules_file):
        time_now = datetime.now().strftime('%Y%m%d-%H%M%S')
        backup_file = '{f}.{d}'.format(f=rules_file, d=time_now)
        log.debug('Creating backup file: {f}'.format(f=backup_file))
        shutil.copy2(rules_file, backup_file)

    # Save the output to the rules file
    log.debug('Creating file: {f}'.format(f=rules_file))
    with open(rules_file, 'w') as f:
        f.write(iptables_out['output'])


def get_remote_host_environment_variable(host, environment_variable):
    """Retrieves the value of an environment variable of a
    remote host over SSH

    :param host: (str) host to query
    :param environment_variable: (str) variable to query
    :return: (str) value of the environment variable
    :raises: TypeError, CommandError
    """
    log = logging.getLogger(mod_logger + '.get_remote_host_environment_variable')
    if not isinstance(host, str):
        msg = 'host argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(environment_variable, str):
        msg = 'environment_variable argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    log.info('Checking host {h} for environment variable: {v}...'.format(h=host, v=environment_variable))
    command = ['ssh', '{h}'.format(h=host), 'echo ${v}'.format(v=environment_variable)]
    try:
        result = run_command(command, timeout_sec=5.0)
        code = result['code']
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if code != 0:
        msg = 'There was a problem checking the remote host {h} over SSH, return code: {c}'.format(
                h=host, c=code)
        log.error(msg)
        raise CommandError(msg)
    else:
        value = result['output'].strip()
        log.info('Environment variable {e} on host {h} value is: {v}'.format(
                e=environment_variable, h=host, v=value))
    return value


def set_remote_host_environment_variable(host, variable_name, variable_value, env_file='/etc/bashrc'):
    """Sets an environment variable on the remote host in the
    specified environment file

    :param host: (str) host to set environment variable on
    :param variable_name: (str) name of the variable
    :param variable_value: (str) value of the variable
    :param env_file: (str) full path to the environment file to set
    :return: None
    :raises: TypeError, CommandError
    """
    log = logging.getLogger(mod_logger + '.set_remote_host_environment_variable')
    if not isinstance(host, str):
        msg = 'host argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(variable_name, str):
        msg = 'variable_name argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(variable_value, str):
        msg = 'variable_value argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(env_file, str):
        msg = 'env_file argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    log.info('Creating the environment file if it does not exist...')
    command = ['ssh', host, 'touch {f}'.format(f=env_file)]
    try:
        result = run_command(command, timeout_sec=5.0)
        code = result['code']
        output = result['output']
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if code != 0:
        msg = 'There was a problem creating environment file {f} on remote host {h} over SSH, ' \
              'exit code {c} and output:\n{o}'.format(h=host, c=code, f=env_file, o=output)
        log.error(msg)
        raise CommandError(msg)

    log.info('Creating ensuring the environment file is executable...')
    command = ['ssh', host, 'chmod +x {f}'.format(f=env_file)]
    try:
        result = run_command(command, timeout_sec=5.0)
        code = result['code']
        output = result['output']
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if code != 0:
        msg = 'There was a problem setting permissions on environment file {f} on remote host {h} over SSH, ' \
              'exit code {c} and output:\n{o}'.format(h=host, c=code, f=env_file, o=output)
        log.error(msg)
        raise CommandError(msg)

    log.info('Adding environment variable {v} with value {n} to file {f}...'.format(
            v=variable_name, n=variable_value, f=env_file))
    command = ['ssh', host, 'echo "export {v}=\\"{n}\\"" >> {f}'.format(f=env_file, v=variable_name, n=variable_value)]
    try:
        result = run_command(command, timeout_sec=5.0)
        code = result['code']
        output = result['output']
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if code != 0:
        msg = 'There was a problem adding variable {v} to environment file {f} on remote host {h} over SSH, ' \
              'exit code {c} and output:\n{o}'.format(h=host, c=code, f=env_file, o=output, v=variable_name)
        log.error(msg)
        raise CommandError(msg)
    else:
        log.info('Environment variable {v} set to {n} on host {h}'.format(v=variable_name, n=variable_value, h=host))


def run_remote_command(host, command, timeout_sec=5.0, port=22, output=True):
    """Retrieves the value of an environment variable of a
    remote host over SSH

    :param host: (str) host to query
    :param command: (str) command
    :param timeout_sec (float) seconds to wait before killing the command
    :param port (int) SSH port to connect on the remote machine
    :param output (bool) Set False to ignore command output
    :return: (str) command output
    :raises: TypeError, CommandError
    """
    log = logging.getLogger(mod_logger + '.run_remote_command')
    if not isinstance(host, str):
        msg = 'host argument must be a string'
        raise TypeError(msg)
    if not isinstance(command, str):
        msg = 'command argument must be a string'
        raise TypeError(msg)
    log.debug('Running remote command on host: {h}: {c}...'.format(h=host, c=command))
    remote_command = ['ssh']
    if port != 22:
        remote_command += ['-p', str(port)]
    remote_command += ['{h}'.format(h=host), '{c}'.format(c=command)]
    try:
        result = run_command(remote_command, timeout_sec=timeout_sec, output=output)
        code = result['code']
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(remote_command))) from exc
    if code != 0:
        msg = 'There was a problem running command [{m}] on host {h} over SSH, return code: {c}, and ' \
              'produced output:\n{o}'.format(h=host, c=code, m=' '.join(remote_command), o=result['output'])
        raise CommandError(msg)
    else:
        output_text = result['output'].strip()
        log.debug('Running command [{m}] host {h} over SSH produced output: {o}'.format(
            m=remote_command, h=host, o=output_text))
        output = {
            'output': output_text,
            'code': code
        }
    return output


def check_remote_host_marker_file(host, file_path):
    """Queries a remote host over SSH to check for existence
    of a marker file

    :param host: (str) host to query
    :param file_path: (str) path to the marker file
    :return: (bool) True if the marker file exists
    :raises: TypeError, CommandError
    """
    log = logging.getLogger(mod_logger + '.check_remote_host_marker_file')
    if not isinstance(host, str):
        msg = 'host argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(file_path, str):
        msg = 'file_path argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    log.debug('Checking host {h} for marker file: {f}...'.format(h=host, f=file_path))
    command = ['ssh', '{h}'.format(h=host), 'if [ -f {f} ] ; then exit 0 ; else exit 1 ; fi'.format(f=file_path)]
    try:
        result = run_command(command, timeout_sec=5.0)
        code = result['code']
        output = result['output']
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if code == 0:
        log.debug('Marker file <{f}> was found on host {h}'.format(f=file_path, h=host))
        return True
    elif code == 1 and output == '':
        log.debug('Marker file <{f}> was not found on host {h}'.format(f=file_path, h=host))
        return False
    else:
        msg = 'There was a problem checking the remote host {h} over SSH for marker file {f}, ' \
              'command returned code {c} and produced output: {o}'.format(
                h=host, f=file_path, c=code, o=output)
        log.debug(msg)
        raise CommandError(msg)


def create_remote_host_marker_file(host, file_path):
    """Creates a marker file on a remote host

    :param host: (str) host to create the file on
    :param file_path: (str) Full path for the file to create
    :return: None
    :raises: TypeError, CommandError
    """
    log = logging.getLogger(mod_logger + '.create_remote_host_marker_file')
    if not isinstance(host, str):
        msg = 'host argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    if not isinstance(file_path, str):
        msg = 'file_path argument must be a string'
        log.error(msg)
        raise TypeError(msg)
    log.debug('Attempting to create marker file {f} on host: {h}...'.format(f=file_path, h=host))
    command = ['ssh', '{h}'.format(h=host), 'touch {f}'.format(f=file_path)]
    try:
        result = run_command(command, timeout_sec=5.0)
        code = result['code']
        output = result['output']
    except CommandError as exc:
        raise CommandError('There was a problem creating marker file: {f}'.format(f=file_path)) from exc
    if code == 0:
        log.info('Marker file {f} successfully created on host {h}'.format(f=file_path, h=host))
    else:
        msg = 'There was a problem creating marker file {f} on remote host {h} over SSH, command returned code {c} ' \
              'and produced output: {o}'.format(h=host, f=file_path, c=code, o=output)
        log.error(msg)
        raise CommandError(msg)


def restore_iptables(firewall_rules):
    """Restores and saves firewall rules from the firewall_rules file

    :param firewall_rules: (str) Full path to the firewall rules file
    :return: None
    :raises OSError
    """
    log = logging.getLogger(mod_logger + '.restore_iptables')
    log.info('Restoring firewall rules from file: {f}'.format(f=firewall_rules))

    # Ensure the firewall rules file exists
    if not os.path.isfile(firewall_rules):
        msg = 'Unable to restore iptables, file not found: {f}'.format(f=firewall_rules)
        log.error(msg)
        raise OSError(msg)

    # Restore the firewall rules
    log.info('Restoring iptables from file: {f}'.format(f=firewall_rules))
    command = ['/sbin/iptables-restore', firewall_rules]
    try:
        result = run_command(command)
    except CommandError as exc:
        msg = 'Unable to restore firewall rules from file: {f}'.format(f=firewall_rules)
        raise OSError(msg) from exc
    log.info('Restoring iptables produced output:\n{o}'.format(o=result['output']))

    # Save iptables
    log.info('Saving iptables...')
    command = ['/etc/init.d/iptables', 'save']
    try:
        result = run_command(command)
    except CommandError as exc:
        msg = 'Unable to save firewall rules'
        raise OSError(msg) from exc
    log.info('Saving iptables produced output:\n{o}'.format(o=result['output']))


def remove_default_gateway():
    """Removes Default Gateway configuration from /etc/sysconfig/network
    and restarts networking
    
    :return: None
    :raises: OSError
    """
    log = logging.getLogger(mod_logger + '.remove_default_gateway')

    # Ensure the network script exists
    network_script = '/etc/sysconfig/network'
    if not os.path.isfile(network_script):
        log.info('Network script not found, nothing to do: {f}'.format(f=network_script))
        return
    log.debug('Found network script: {f}'.format(f=network_script))

    # Remove settings for GATEWAY and GATEWAYDEV
    log.info('Attempting to remove any default gateway configurations...')
    for line in fileinput.input(network_script, inplace=True):
        if re.search('^GATEWAY=.*', line):
            log.info('Removing GATEWAY line: {li}'.format(li=line))
        elif re.search('^GATEWAYDEV=.*', line):
            log.info('Removing GATEWAYDEV line: {li}'.format(li=line))
        else:
            log.debug('Keeping line: {li}'.format(li=line))
            sys.stdout.write(line)

    # Restart networking for the changes to take effect
    log.info('Restarting the network service...')
    try:
        service_network_restart()
    except CommandError as exc:
        raise OSError('Attempted unsuccessfully to restart networking') from exc
    else:
        log.info('Successfully restarted networking')


def is_systemd():
    """Determines whether this system uses systemd

    :return: (bool) True if this distro has systemd
    """
    os_family = platform.system()
    if os_family != 'Linux':
        raise OSError('This method is only supported on Linux, found OS: {o}'.format(o=os_family))
    if os.path.exists('/bin/systemctl'):
        return True
    else:
        return False


def manage_service(service_name, service_action='status', systemd=None, output=True):
    """Use to run Linux sysv or systemd service commands

    :param service_name (str) name of the service to start
    :param service_action (str) action to perform on the service
    :param systemd (bool) True if the command should use systemd
    :param output (bool) True to print output
    :return: None
    :raises: OSError
    """
    log = logging.getLogger(mod_logger + '.manage_service')

    # Ensure the service name is a string
    if not isinstance(service_name, str):
        raise OSError('service_name arg must be a string, found: {t}'.format(t=service_name.__class__.__name__))

    # Ensure the service name is a string
    if not isinstance(service_action, str):
        raise OSError('service_action arg must be a string, found: {t}'.format(t=service_name.__class__.__name__))

    # Ensure the service action is valid
    valid_actions = ['start', 'stop', 'reload', 'restart', 'status', 'enable', 'disable']
    service_action = service_action.lower().strip()
    if service_action not in valid_actions:
        raise OSError('Invalid service action requested [{a}], valid actions are: [{v}]'.format(
            a=service_action, v=','.join(valid_actions)
        ))
    log.info('Attempting to [{a}] service: {s}'.format(a=service_action, s=service_name))

    # If systemd was not provided, attempt to determine which method to use
    if not systemd:
        log.debug('Systemd not provided, attempting to determine which method to use...')
        systemd = is_systemd()

    # Create commands depending on the method
    command_list = []
    if systemd:
        if not service_name.endswith('.service'):
            service_name = '{s}.service'.format(s=service_name)
        log.info('Attempting to manage service with systemd: {s}'.format(s=service_name))
        command_list.append(['/usr/bin/systemctl', service_action, service_name])
    else:
        log.info('Attempting to manage service with sysv: {s}'.format(s=service_name))

        # Determine the commands to run
        if service_action == 'enable':
            command_list.append(['/sbin/chkconfig', '--add', service_name])
            command_list.append(['/sbin/chkconfig', service_name, 'on'])
        elif service_action == 'disable':
            command_list.append(['/sbin/chkconfig', service_name, 'off'])
        else:
            command_list.append(['/sbin/service', service_name, service_action])

    # Run the commands in the command list
    post_command_wait_time_sec = 3
    for command in command_list:
        log.info('Attempting to run command: [{c}]'.format(c=' '.join(command)))
        try:
            result = run_command(command, timeout_sec=30, output=output)
        except CommandError as exc:
            raise OSError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
        log.info('Command exited with code: {c}'.format(c=str(result['code'])))
        if result['code'] != 0:
            raise OSError('Command exited with a non-zero code: [{c}], and produced output:\n{o}'.format(
                c=str(result['code']), o=result['output']))
        else:
            log.info('Command returned successfully with output:\n{o}'.format(o=result['output']))
        log.info('Waiting {t} sec...'.format(t=str(post_command_wait_time_sec)))
        time.sleep(post_command_wait_time_sec)


def system_reboot(wait_time_sec=20):
    """Reboots the system after a specified wait time.  Must be run as root

    :param wait_time_sec: (int) number of sec to wait before performing the reboot
    :return: None
    :raises: SystemRebootError, SystemRebootTimeoutError
    """
    log = logging.getLogger(mod_logger + '.system_reboot')

    try:
        wait_time_sec = int(wait_time_sec)
    except ValueError:
        raise CommandError('wait_time_sec must be an int, or a string convertible to an int')

    log.info('Waiting {t} seconds before reboot...'.format(t=str(wait_time_sec)))
    time.sleep(wait_time_sec)
    command = ['shutdown', '-r', 'now']
    log.info('Shutting down with command: [{c}]'.format(c=' '.join(command)))
    time.sleep(2)
    log.info('Shutting down...')
    try:
        result = run_command(command=command, timeout_sec=60)
    except CommandError as exc:
        raise SystemRebootError(
            'There was a problem running shutdown command: [{c}]'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        msg = 'Shutdown command exited with a non-zero code: [{c}], and produced output:\n{o}'.format(
            c=str(result['code']), o=result['output'])
        raise SystemRebootError(msg)
    log.info('Waiting 60 seconds to ensure the reboot completes...')
    time.sleep(60)
    msg = 'Reboot has not completed after 60 seconds'
    log.error(msg)
    raise SystemRebootTimeoutError(msg)


def create_user_basic(username, uid=None):
    """Creates a user with default settings

    :param username: (str) username
    :param uid: (int) desired UID for the new user
    :return: None
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.create_user_basic')
    log.info('Attempting to create user with username: {u}'.format(u=username))
    command = ['useradd', username]
    if uid:
        command += ['-u', str(uid)]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem creating user: {u}'.format(u=username)) from exc
    if result['code'] == 9:
        log.info('useradd exited with code 9, User already exists: {u}'.format(u=username))
    elif result['code'] != 0:
        raise CommandError('useradd exited with code: {c}\n{o}'.format(c=str(result['code']), o=result['output']))
    log.info('User created: {u}'.format(u=username))


def remove_user_password(username):
    """Removes password for a user

    :param username: (str) username
    :return: None
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.remove_user_password')
    log.info('Attempting to remove password for username: {u}'.format(u=username))
    command = ['passwd', '-d', username]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem deleting password for user: {u}'.format(u=username)) from exc
    if result['code'] != 0:
        raise CommandError('passwd exited with code: {c}'.format(c=str(result['code'])))
    log.info('Password removed for user: {u}'.format(u=username))


def set_group_id(group_name, new_id):
    """Sets the group name to the provided new group ID

    :param group_name: (str) group name
    :param new_id: (int) new ID for the group
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.set_group_id')
    command = ['groupmod', '-g', str(new_id), group_name]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem setting ID for group [{g}]: {i}'.format(g=group_name, i=str(new_id))) from exc
    if result['code'] != 0:
        raise CommandError('groupmod exited with code: {c}\n{o}'.format(
            c=str(result['code']), o=result['output']))
    log.info('Set ID for group [{g}]: {i}'.format(g=group_name, i=str(new_id)))


def set_user_id(username, new_id):
    """Sets the username to the provided new user ID

    :param username: (str) user name
    :param new_id: (int) new ID for the user
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.set_user_id')
    command = ['usermod', '-u', str(new_id), username]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem setting ID for user [{u}]: {i}'.format(u=username, i=str(new_id))) from exc
    if result['code'] != 0:
        raise CommandError('usermod exited with code: {c}\n{o}'.format(
            c=str(result['code']), o=result['output']))
    log.info('Set ID for user [{u}]: {i}'.format(u=username, i=str(new_id)))


def main():
    """Sample usage for this python module

    This main method simply illustrates sample usage for this python
    module.

    :return: None
    """
    mkdir_p('/tmp/test/test')
    source('/root/.bash_profile')
    yum_install(['httpd', 'git'])
    yum_install(['httpd', 'git'], dest_dir='/tmp/test/test', downloadonly=True)
    sed('/Users/yennaco/Downloads/homer_testing/network', '^HOSTNAME.*', 'HOSTNAME=foo.joe')
    test_script = '/Users/yennaco/Downloads/homer/script.sh'
    results = run_command([test_script], timeout_sec=1000)
    print('Script {s} produced exit code [{c}] and output:\n{o}'.format(
        s=test_script, c=results['code'], o=results['output']))


if __name__ == '__main__':
    main()
