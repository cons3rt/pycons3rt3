#!/usr/bin/python

"""Module: osutil

This module initializes the pycons3rt directories and provides
OS-agnostic resources
"""
import platform
import os
import sys
import errno
import traceback

__author__ = 'Joe Yennaco'


default_logging_conf_file_contents = '''[loggers]
keys=root

[handlers]
keys=stream_handler,file_handler_info,file_handler_debug,file_handler_warn

[formatters]
keys=formatter_info,formatter_debug

[logger_root]
level=DEBUG
handlers=stream_handler,file_handler_info,file_handler_debug,file_handler_warn

[handler_stream_handler]
class=StreamHandler
level=INFO
formatter=formatter_info
args=(sys.stderr,)

[handler_file_handler_info]
class=FileHandler
level=INFO
formatter=formatter_info
args=('REPLACE_LOG_DIRpycons3rt-info.log', 'a')

[handler_file_handler_debug]
class=FileHandler
level=DEBUG
formatter=formatter_debug
args=('REPLACE_LOG_DIRpycons3rt-debug.log', 'a')

[handler_file_handler_warn]
class=FileHandler
level=WARN
formatter=formatter_debug
args=('REPLACE_LOG_DIRpycons3rt-warn.log', 'a')

[formatter_formatter_info]
format=%(asctime)s [%(levelname)s] %(name)s - %(message)s

[formatter_formatter_debug]
format=%(asctime)s [%(levelname)s] %(name)s <%(threadName)s> - %(message)s
'''

replace_str = 'REPLACE_LOG_DIR'


def get_os():
    """Returns the OS based on platform.sysyen

    :return: (str) OS family
    """
    return platform.system()


def get_dest_dir(dest_dir=None):
    """Determine the full path to the destination directory on the OS

    :param dest_dir: (str) [OPTIONAL] Destination directory, can start with `~` as the home directory
    :return: (str) Full path to the destination directory
    """
    if dest_dir:
        dest_dir_provided = dest_dir.strip()

        # Handle ~ as the leading char if provided
        if dest_dir_provided.startswith('~'):
            dest_dir = str(dest_dir_provided.replace('~', os.path.expanduser('~')))
        else:
            dest_dir = str(dest_dir_provided)
    else:
        dest_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        if not os.path.isdir(dest_dir):
            dest_dir = os.path.join(os.path.expanduser('~'), 'Download')
        if not os.path.isdir(dest_dir):
            dest_dir = os.path.expanduser('~')

    # Ensure the destination directory is found
    if not os.path.isdir(dest_dir):
        print('ERROR: Destination directory not found: {d}'.format(d=dest_dir))
        return None
    return dest_dir


def get_pycons3rt_home_dir():
    """Checks for PYCONS3RT_HOME first, and if not set or it does not exist
    returns the default pycons3rt home directory based on OS

    :return: (str) Full path to pycons3rt home
    :raises: OSError
    """
    if 'PYCONS3RT_HOME' in os.environ.keys():
        if os.path.isdir(os.environ['PYCONS3RT_HOME']):
            return os.environ['PYCONS3RT_HOME']
    user_login = True
    user_home_dir = os.path.expanduser('~')
    if user_home_dir == '~' or not os.path.isdir(user_home_dir):
        user_login = False
    if platform.system() == 'Linux' and user_login:
        return os.path.join(user_home_dir, '.cons3rt')
    elif platform.system() == 'Linux' and not user_login:
        return os.path.join(os.sep, 'root', '.cons3rt')
    elif platform.system() == 'Windows' and user_login:
        return os.path.join(user_home_dir, '.cons3rt')
    elif platform.system() == 'Windows' and not user_login:
        return os.path.join('C:', os.path.sep, 'cons3rt')
    elif platform.system() == 'Darwin':
        return os.path.join(user_home_dir, '.cons3rt')
    else:
        raise OSError('Unsupported Operating System')


def get_pycons3rt_user_dir():
    """Returns the pycons3rt user-writable home dir

    :return: (str) Full path to the user-writable pycons3rt home
    """
    user_home_dir = os.path.expanduser('~')
    if user_home_dir == '~' or not os.path.isdir(user_home_dir):
        return
    else:
        return os.path.join(user_home_dir, '.cons3rt')


def get_pycons3rt_log_dir():
    """Returns the pycons3rt log directory

    :return: (str) Full path to pycons3rt log directory
    :raises: OSError
    """
    return os.path.join(get_pycons3rt_home_dir(), 'log')


def get_pycons3rt_scripts_dir():
    """Returns the pycons3rt log directory

    :return: (str) Full path to pycons3rt log directory
    :raises: OSError
    """
    return os.path.join(get_pycons3rt_home_dir(), 'scripts')


def get_pycons3rt_conf_dir():
    """Returns the pycons3rt conf directory

    :return: (str) Full path to pycons3rt conf directory
    """
    return os.path.join(get_pycons3rt_home_dir(), 'conf')


def get_pycons3rt_data_dir():
    """Returns the pycons3rt data directory

    :return: (str) Full path to pycons3rt data directory
    """
    return os.path.join(get_pycons3rt_home_dir(), 'data')


def get_pycons3rt_src_dir():
    """Returns the pycons3rt src directory

    :return: (str) Full path to pycons3rt src directory
    """
    return os.path.join(get_pycons3rt_home_dir(), 'src')


def initialize_pycons3rt_dirs():
    """Initializes the pycons3rt directories

    :return: None
    :raises: OSError
    """
    for pycons3rt_dir in [get_pycons3rt_home_dir(),
                          get_pycons3rt_conf_dir(),
                          get_pycons3rt_data_dir(),
                          get_pycons3rt_log_dir(),
                          get_pycons3rt_src_dir()]:
        if os.path.isdir(pycons3rt_dir):
            continue
        try:
            os.makedirs(pycons3rt_dir)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(pycons3rt_dir):
                pass
            else:
                msg = 'Unable to create directory: {d}'.format(d=pycons3rt_dir)
                raise OSError(msg)


def main():
    # Create the pycons3rt directories
    try:
        initialize_pycons3rt_dirs()
    except OSError:
        traceback.print_exc()
        return 1

    # Replace log directory paths
    log_dir_path = get_pycons3rt_log_dir() + os.path.sep
    conf_contents = default_logging_conf_file_contents.replace(replace_str, log_dir_path)

    # Create the logging config file
    logging_config_file_dest = os.path.join(get_pycons3rt_conf_dir(), 'pycons3rt-logging.conf')
    with open(logging_config_file_dest, 'w') as f:
        f.write(conf_contents)
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
