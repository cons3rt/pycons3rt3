#!/usr/bin/env python3

"""Module: service_runner

Contains classes and methods for the CONS3RT service runner framework, which allows users
to execute functions in AWS or Azure not integrated into the main CONS3RT application.

service_runner.RunMonitor.monitor takes the arg: func_tasks has the following requirements:

* A function must be passed in as func_tasks
* Must be executable with no args provided
* Raises ServiceRunnerError if an error is detected
* Returns a dict with the following:

{
  'result': 'SUCCESS|ERROR'
  'output': 'FORMATTED OUTPUT FOR OUTPUT FILE'
}


"""
import datetime
import logging
import os
import threading
import time
import traceback

from .exceptions import ServiceRunnerError
from .logify import Logify
from .slack import SlackAttachment, SlackMessage


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.service_runner'

# Default runner dir
runner_dir_default = os.path.join(os.sep, 'home', 'runner')


class RunMonitor(object):
    """Monitors for Script ETT execution
    """

    def __init__(self, runner_dir=runner_dir_default):
        self.cls_logger = mod_logger + '.RunMonitor'
        self.stop_monitoring = False
        self.check_interval_sec = 15
        self.thread_monitor_interval_sec = 30
        self.thread_monitor_warn_time_sec = 3600
        self.run_release_time_sec = 600
        # Directories and files
        self.runner_dir = runner_dir
        self.results_dir = os.path.join(self.runner_dir, 'results')

        # Marker files
        self.go_marker_file = os.path.join(self.runner_dir, 'GO')
        self.complete_marker_file = os.path.join(self.runner_dir, 'COMPLETE')
        self.error_marker_file = os.path.join(self.runner_dir, 'ERROR_DETECTED')

    def stop(self):
        self.stop_monitoring = True

    def monitor(self, func_tasks, slack_webhook_url=None, slack_channel_monitor=None, slack_channel_alert=None,
                slack_text=None):
        """Monitors for the GO file

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.monitor')

        log.info('Starting monitor...')
        while not self.stop_monitoring:
            log.info('Checking for marker file: {f}'.format(f=self.go_marker_file))

            # Check for existence of the GO marker files
            if os.path.isfile(self.go_marker_file):
                os.remove(self.go_marker_file)

                # Remove other marker files if found
                for marker_file in [self.complete_marker_file, self.error_marker_file]:
                    if os.path.isfile(marker_file):
                        log.info('Removing marker file: {f}'.format(f=marker_file))
                        os.remove(marker_file)

                log.info('GO marker file found, starting a runner thread...')
                runner = ScriptRunner(
                    func_tasks=func_tasks,
                    results_dir=self.results_dir,
                    error_marker_file=self.error_marker_file,
                    complete_marker_file=self.complete_marker_file,
                    slack_webhook_url=slack_webhook_url,
                    slack_channel_monitor=slack_channel_monitor,
                    slack_channel_alert=slack_channel_alert,
                    slack_text=slack_text
                )
                runner.start()
                start_time = time.time()

                while runner.is_alive():
                    elapsed_time_sec = round((time.time() - start_time))

                    if elapsed_time_sec <= self.thread_monitor_warn_time_sec:
                        log.info('Deployment in progress, time elapsed: {t}'.format(t=str(elapsed_time_sec)))
                    else:
                        log.warning('Deployment in progress may be delayed, time elapsed: {t}'.format(
                            t=str(elapsed_time_sec)))
                    time.sleep(self.thread_monitor_interval_sec)
            time.sleep(self.check_interval_sec)


class ScriptRunner(threading.Thread):
    """Performs an execution of tasks for this script ETT via the passed function
    """

    def __init__(self, func_tasks, results_dir, error_marker_file, complete_marker_file, slack_webhook_url=None,
                 slack_channel_monitor=None, slack_channel_alert=None, slack_text=None):
        threading.Thread.__init__(self)
        self.cls_logger = mod_logger + '.ScriptRunner'
        self.timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        self.func_tasks = func_tasks
        self.results_dir = results_dir
        self.error_marker_file = error_marker_file
        self.complete_marker_file = complete_marker_file
        self.slack_webhook_url = slack_webhook_url
        self.slack_channel_monitor = slack_channel_monitor
        self.slack_channel_alert = slack_channel_alert
        self.slack_text = slack_text
        if all([slack_webhook_url, slack_channel_monitor, slack_channel_alert, slack_text]):
            self.slack_msg = SlackMessage(
                slack_webhook_url,
                channel=slack_channel_monitor,
                text=self.timestamp + ': ' + self.slack_text
            )
        else:
            self.slack_msg = None
        self.output = None

    def verify_prereqs(self):
        """Verifying prerequisites exist to run

        :return:
        """
        log = logging.getLogger(self.cls_logger + '.verify_prereqs')
        # Verify directories exist
        required_dirs = [self.results_dir]
        for required_dir in required_dirs:
            if not os.path.isdir(required_dir):
                log.error('Directory not found: {d}'.format(d=required_dir))
                return False
        return True

    def run(self):
        """Execute the tasks

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.run')
        if not self.verify_prereqs():
            self.report_fail(msg='Missing prerequisite')
            return

        # Run the Service deployment
        log.info('Running the service runner function tasks...')
        try:
            function_output = self.func_tasks()
        except ServiceRunnerError as exc:
            fail_msg = 'Problem running service runner tasks\n{e}\n{t}'.format(e=str(exc), t=traceback.format_exc())
            self.report_fail(msg=fail_msg)
        else:
            if 'output' in function_output.keys():
                content = function_output['output']
            else:
                content = None

            if 'result' in function_output.keys():
                if function_output['result'].upper() == 'ERROR':
                    self.report_fail(msg='Service runner tasks completed with error', content=str(content))
                else:
                    self.report_success(msg='Completed running service runner tasks successfully', content=str(content))
            else:
                self.report_success(msg='Completed running service runner tasks with no result', content=str(content))

    def create_output_file(self, msg, content):
        """Creates the log file for test results

        :param msg (str) message
        :param content (str) output file content
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.create_output_file')
        output_file = os.path.join(self.results_dir, 'output_{t}.log'.format(t=self.timestamp))
        log.info('Generating output file: {f}'.format(f=output_file))
        with open(output_file, 'w') as f:
            f.write(msg)
            f.write('\n\n')
            f.write(content)
            f.write('\n')

    def report_fail(self, msg, content=None):
        """Reports failure

        :param msg (str) failure message
        :param content (str) output file content
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.report_fail')
        log_msg = msg
        if content:
            self.create_output_file(msg, content)
            log_msg += '\n' + content
        log.error(log_msg)
        with open(self.error_marker_file, 'a+') as f:
            f.write(msg)
        self.slack_msg.set_channel(channel=self.slack_channel_alert)
        attachment = SlackAttachment(fallback=msg, text=msg, color='danger')
        self.slack_msg.add_attachment(attachment)
        self.slack_msg.send()

    def report_success(self, msg, content=None):
        """Reports success

        :param msg (str) success message
        :param content (str) output file content
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.report_success')
        log_msg = msg
        if content:
            self.create_output_file(msg, content)
            log_msg += '\n' + content
        log.info(log_msg)
        with open(self.complete_marker_file, 'a+') as f:
            f.write(msg)
        attachment = SlackAttachment(fallback=msg, text=msg, color='good')
        self.slack_msg.set_channel(channel=self.slack_channel_monitor)
        self.slack_msg.add_attachment(attachment)
        self.slack_msg.send()


def read_service_config(service_config_file):
    """Reads the config properties file for the service

    This method reads the config properties file for a service and returns a dict

    :param service_config_file: (str) path to the Service config file
    :return: (dict) key-value pairs from the properties file
    """
    log = logging.getLogger(mod_logger + '.read_service_config')
    properties = {}

    # Ensure the Service config props file exists
    if not os.path.isfile(service_config_file):
        log.error('Service config file not found: {f}'.format(f=service_config_file))
        return properties

    log.info('Reading Service config properties file: {r}'.format(r=service_config_file))
    with open(service_config_file, 'r') as f:
        for line in f:
            if line.startswith('#'):
                continue
            elif '=' in line:
                split_line = line.strip().split('=', 1)
                if len(split_line) == 2:
                    prop_name = split_line[0].strip()
                    prop_value = split_line[1].strip()
                    if prop_name is None or not prop_name or prop_value is None or not prop_value:
                        log.info('Property name <{n}> or value <v> is none or blank, not including it'.format(
                            n=prop_name, v=prop_value))
                    else:
                        log.debug('Adding property {n} with value {v}...'.format(n=prop_name, v=prop_value))
                        unescaped_prop_value = prop_value.replace('\\', '')
                        properties[prop_name] = unescaped_prop_value
                else:
                    log.warning('Skipping line that did not split into 2 part on an equal sign...')
    log.info('Successfully read in service config properties')
    log.info('Removing: {f}'.format(f=service_config_file))
    os.remove(service_config_file)
    return properties
