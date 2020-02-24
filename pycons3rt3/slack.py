#!/usr/bin/python

"""Module: slack

This module provides an interface for posting to Slack!

Sample usage:

python slack.py \
    --text="This is the text of my message" \
    --url="https://hooks.slack.com/services/my-webhook-url" \
    --attachment="Attachment text" \
    --channel="@joe.yennaco" \
    --color=good \
    --pretext="This is pretext" \
    --icon="https://s3.amazonaws.com/jackpine-images/homer-flexing.jpg"

Or use the slack CLI command:

slack \
--url="https://hooks.slack.com/services/my-webhook-url" \
--text="HELLO WORLD!" \
--channel="#helpful"

"""
import logging
import json
import argparse
import os

import requests

# Set up logger name for this module
try:
    from .logify import Logify
except ImportError:
    Logify = None
    mod_logger = 'slack'
else:
    mod_logger = Logify.get_name() + '.slack'

try:
    from .deployment import Deployment
except ImportError:
    Deployment = None

from .exceptions import Cons3rtSlackerError

__author__ = 'Joe Yennaco'


class SlackMessage(object):
    """Object to encapsulate a Slack message

    This class encapsulates a Slack message and its parameters, and
    provides a send() method for sending Slack messages
    """
    def __init__(self, webhook_url, text, **kwargs):
        """Creates a SlackMessage object

        :param webhook_url: (str) Webhook URL provided by Slack
        :param text: (str) Text to send in the Slack message
        :param kwargs:
        :return: None
        :raises ValueError
        """
        self.cls_logger = mod_logger + '.SlackMessage'
        log = logging.getLogger(self.cls_logger + '.__init__')
        self.payload = {}
        if not isinstance(webhook_url, str):
            raise ValueError('webhook_url arg must be a string')
        if not isinstance(text, str):
            raise ValueError('text arg must be a string')
        self.payload['text'] = text
        self.webhook_url = webhook_url
        self.options = ['user', 'channel', 'icon_url', 'icon_emoji']
        self.attachments = []
        for option in self.options:
            if (option in kwargs) and (isinstance(option, str)):
                self.payload[option] = kwargs[option]
        log.debug('SlackMessage configured using webhook URL: {u}'.format(
            u=self.webhook_url))

    def __str__(self):
        return self.payload.__str__()

    def set_text(self, text):
        """Sets the text attribute of the payload

        :param text: (str) Text of the message
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_text')
        if not isinstance(text, str):
            msg = 'text arg must be a string'
            log.error(msg)
            raise ValueError(msg)
        self.payload['text'] = text
        log.debug('Set message text to: {t}'.format(t=text))

    def set_icon(self, icon_url):
        """Sets the icon_url for the message

        :param icon_url: (str) Icon URL
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_icon')
        if not isinstance(icon_url, str):
            msg = 'icon_url arg must be a string'
            log.error(msg)
            raise ValueError(msg)
        self.payload['icon_url'] = icon_url
        log.debug('Set Icon URL to: {u}'.format(u=icon_url))

    def set_channel(self, channel):
        """Sets the channel for the message

        :param channel: (str) Slack channel name
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_channel')
        if not isinstance(channel, str):
            msg = 'channel arg must be a string'
            log.error(msg)
            raise ValueError(msg)
        self.payload['channel'] = channel
        log.debug('Set channel to: {c}'.format(c=channel))

    def add_attachment(self, attachment):
        """Adds an attachment to the SlackMessage payload

        This public method adds a slack message to the attachment
        list.

        :param attachment: SlackAttachment object
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.add_attachment')
        if not isinstance(attachment, SlackAttachment):
            msg = 'attachment must be of type: SlackAttachment'
            log.error(msg)
            raise ValueError(msg)
        self.attachments.append(attachment.attachment)
        log.debug('Added attachment: {a}'.format(a=attachment))

    def send(self):
        """Sends the Slack message

        This public method sends the Slack message along with any
        attachments, then clears the attachments array.

        :return: None
        :raises: OSError
        """
        log = logging.getLogger(self.cls_logger + '.send')

        if self.attachments:
            self.payload['attachments'] = self.attachments

        # Encode payload in JSON
        log.debug('Using payload: %s', self.payload)
        try:
            json_payload = json.JSONEncoder().encode(self.payload)
        except(TypeError, ValueError, OverflowError) as exc:
            msg = 'There was a problem encoding the JSON payload'
            raise OSError(msg) from exc
        else:
            log.debug('JSON payload: %s', json_payload)

        # Post to Slack!
        log.debug('Posting message to Slack...')
        try:
            result = requests.post(url=self.webhook_url, data=json_payload)
        except requests.exceptions.ConnectionError as exc:
            msg = 'There was a problem posting to Slack'
            raise OSError(msg) from exc

        # Check return code
        if result.status_code != 200:
            log.error('Slack post to url {u} failed with code: {c}'.format(c=result.status_code, u=self.webhook_url))
        else:
            log.debug('Posted message to Slack successfully.')

        # Clear out attachments after sending
        self.attachments = []
        self.payload.pop('attachments', None)


class SlackAttachment(object):
    """Contains data for a Slack Attachment

    This class is used to create an attachment for a Slack
    post.
    """
    def __init__(self, fallback, **kwargs):
        self.cls_logger = mod_logger + '.SlackAttachment'
        if not isinstance(fallback, str):
            raise ValueError('fallback arg must be a string')
        self.fallback = fallback
        self.attachment = {}
        self.options = ['color', 'pretext', 'author_name', 'author_link',
                        'author_icon', 'title', 'title_link', 'text',
                        'image_url', 'thumb_url']
        for option in self.options:
            if (option in kwargs) and (isinstance(option, str)):
                self.attachment[option] = kwargs[option]
        if 'fields' in kwargs:
            if isinstance(kwargs['fields'], list):
                for field in kwargs['fields']:
                    if not isinstance(field, dict):
                        raise ValueError('field entries must be of type: dict')
                    for key, value in field.items():
                        if not isinstance(value, str):
                            raise ValueError('field values must be strings')
                self.attachment['fields'] = kwargs['fields']

    def __str__(self):
        return self.fallback


class Cons3rtSlacker(SlackMessage):

    def __init__(self, slack_url):
        self.cls_logger = mod_logger + '.Cons3rtSlacker'
        self.slack_url = slack_url
        self.dep = Deployment()
        self.slack_channel = self.dep.get_value('SLACK_CHANNEL')
        self.deployment_run_name = self.dep.get_value('cons3rt.deploymentRun.name')
        self.deployment_run_id = self.dep.get_value('cons3rt.deploymentRun.id')

        # Build the Slack message text
        self.slack_text = 'Run: ' + self.deployment_run_name + ' (ID: ' + self.deployment_run_id + ')' + '\nHost: *' + \
                          self.dep.cons3rt_role_name + '*'

        # Initialize the SlackMessage
        try:
            SlackMessage.__init__(self, webhook_url=self.slack_url, text=self.slack_text, channel=self.slack_channel)
        except ValueError:
            raise

    def send_cons3rt_agent_logs(self):
        """Sends a Slack message with an attachment for each cons3rt agent log

        :return:
        """
        log = logging.getLogger(self.cls_logger + '.send_cons3rt_agent_logs')

        log.debug('Searching for log files in directory: {d}'.format(d=self.dep.cons3rt_agent_log_dir))
        for item in os.listdir(self.dep.cons3rt_agent_log_dir):
            item_path = os.path.join(self.dep.cons3rt_agent_log_dir, item)
            if os.path.isfile(item_path):
                log.debug('Adding slack attachment with cons3rt agent log file: {f}'.format(f=item_path))
                try:
                    with open(item_path, 'r') as f:
                        file_text = f.read()
                except (IOError, OSError) as exc:
                    log.warning('There was a problem opening file: {f}\n{e}'.format(f=item_path, e=str(exc)))
                    continue

                # Take the last 7000 characters
                file_text_trimmed = file_text[-7000:]
                attachment = SlackAttachment(fallback=file_text_trimmed, text=file_text_trimmed, color='#9400D3')
                self.add_attachment(attachment)
        self.send()

    def send_text_file(self, text_file):
        """Sends a Slack message with the contents of a text file

        :param: test_file: (str) Full path to text file to send
        :return: None
        :raises: Cons3rtSlackerError
        """
        log = logging.getLogger(self.cls_logger + '.send_text_file')

        if not isinstance(text_file, str):
            msg = 'arg text_file must be a string, found type: {t}'.format(t=text_file.__class__.__name__)
            raise Cons3rtSlackerError(msg)

        if not os.path.isfile(text_file):
            msg = 'The provided text_file was not found or is not a file: {f}'.format(f=text_file)
            raise Cons3rtSlackerError(msg)

        log.debug('Attempting to send a Slack message with the contents of file: {f}'.format(f=text_file))
        try:
            with open(text_file, 'r') as f:
                file_text = f.read()
        except (IOError, OSError) as exc:
            msg = 'There was a problem opening file: {f}'.format(f=text_file)
            raise Cons3rtSlackerError(msg) from exc

        # Take the last 7000 characters
        file_text_trimmed = file_text[-7000:]
        attachment = SlackAttachment(fallback=file_text_trimmed, text=file_text_trimmed, color='#9400D3')
        self.add_attachment(attachment)
        self.send()


def main():
    """Handles external calling for this module

    Execute this python module and provide the args shown below to
    external call this module to send Slack messages with attachments!

    :return: None
    """
    log = logging.getLogger(mod_logger + '.main')
    parser = argparse.ArgumentParser(description='This Python module allows '
                                                 'sending Slack messages.')
    parser.add_argument('-u', '--url', help='Slack webhook URL', required=True)
    parser.add_argument('-t', '--text', help='Text of the message', required=True)
    parser.add_argument('-n', '--channel', help='Slack channel', required=True)
    parser.add_argument('-i', '--icon', help='URL for the Slack icon', required=False)
    parser.add_argument('-c', '--color', help='Color of the Slack post', required=False)
    parser.add_argument('-a', '--attachment', help='Text for the Slack Attachment', required=False)
    parser.add_argument('-p', '--pretext', help='Pretext for the Slack attachment', required=False)
    args = parser.parse_args()

    # Create the SlackMessage object
    try:
        slack_msg = SlackMessage(args.url, channel=args.channel, icon_url=args.icon, text=args.text)
    except ValueError as e:
        msg = 'Unable to create slack message\n{ex}'.format(ex=e)
        log.error(msg)
        print(msg)
        return

    # If provided, create the SlackAttachment object
    if args.attachment:
        try:
            slack_att = SlackAttachment(fallback=args.attachment, color=args.color,
                                        pretext=args.pretext, text=args.attachment)
        except ValueError as exc:
            log.error('Unable to create slack attachment\n{e}'.format(e=str(exc)))
            return
        slack_msg.add_attachment(slack_att)

    # Send Slack message
    try:
        slack_msg.send()
    except(TypeError, ValueError, IOError) as exc:
        log.error('Unable to send Slack message\n{e}'.format(e=str(exc)))
        return
    log.debug('Your message has been Slacked successfully!')


if __name__ == '__main__':
    main()
