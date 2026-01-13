#!/usr/bin/python
"""Module: teams

This module provides an interface for posting to Microsoft Teams! (sorry!)

Sample usage:

python teams.py \
    --text="This is the text of my message" \
    --url="https://prod-39.usgovtexas.logic.azure.us:443/workflows/<hook_url>" \
    --type="text"

Or use the teams CLI command:

teams \
    --url="https://prod-39.usgovtexas.logic.azure.us:443/workflows/<hook_url>" \
    --text="HELLO WORLD!" \
    --type="text"

References:
  - https://techcommunity.microsoft.com/discussions/teamsdeveloper/simple-workflow-to-replace-teams-incoming-webhooks/4225270

"""
import logging
import json
import argparse
import os
import sys
import traceback
from copy import deepcopy

import requests

# Set up logger name for this module
try:
    from .logify import Logify
except ImportError:
    Logify = None
    mod_logger = 'teams'
else:
    mod_logger = Logify.get_name() + '.teams'

try:
    from .deployment import Deployment
except ImportError:
    Deployment = None

from .exceptions import Cons3rtTeamsError


__author__ = 'Joe Yennaco'


# Check for the existence of the TEAMS_HOOK environment variable
# as a fallback for the webhook URL
teams_hook_env_var = os.getenv('TEAMS_HOOK')


# Template for constructing Teams cards
#    NOTE: payload text is limited to 28k
card_template = {
    'type':'message',
    'attachments':[{
        'contentType':'application/vnd.microsoft.card.adaptive',
        'content':{
            '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json',
            'type': 'AdaptiveCard',
            'version': '1.5',
            'body':[]
        }
    }]
}


# Emoji for use in Teams messages
emoji = {
    'boom': '&#128165;',
    'bus': '&#128652;',
    'construction': '&#127959;',
    'safety': '&#x1F512;',

    # Status / semantics
    'success': '&#9989;',     # ✅
    'warning': '&#9888;',     # ⚠️
    'error': '&#10060;',      # ❌
    'info': '&#8505;'         # ℹ️
}


# Colors for use in Microsoft Teams Adaptive Card TextBlock messages
# Maps friendly names to valid Adaptive Cards `color` values
textblock_colors = {
    'default': 'Default',
    'dark': 'Dark',
    'light': 'Light',

    # Semantic / status colors
    'ok': 'Good',          # success / healthy
    'good': 'Good',
    'success': 'Good',

    'warning': 'Warning',  # caution / needs attention
    'caution': 'Warning',

    'danger': 'Attention', # error / failure / critical
    'error': 'Attention',
    'critical': 'Attention',

    # Emphasis / UI accents
    'accent': 'Accent',    # Teams theme color
    'highlight': 'Accent'
}


# Valid message types
valid_message_types = [
    'card',
    'code',
    'text'
]


# Valid message levels
valid_message_levels = [
    'error',
    'info',
    'success',
    'warning',
]


class TeamsMessage(object):
    """Object to encapsulate a Teams message webhook

    This class encapsulates a Teams message and its parameters, and
    provides multiple send() methods for sending Teams messages
    of variable types
    """
    def __init__(self, webhook_url=None, **kwargs):
        """Creates a TeamsMessage object

        :param webhook_url: (str) Webhook URL provided by Teams Workflows
        :raises ValueError
        """
        self.cls_logger = mod_logger + '.TeamsMessage'
        self.webhook_url = webhook_url
        self.level = 'default'
        self.text = None
        self.title = None
        self.type = None
        self.payload = {}
        self.card_body_items = []

        # If the webhook URL is not provided, check for the TEAMS_HOOK environment variable
        if not self.webhook_url:
            self.webhook_url = teams_hook_env_var
        if not isinstance(self.webhook_url, str):
            raise ValueError('webhook_url arg must be a string')
        
        # Set optional args if provided
        if 'text' in kwargs and isinstance(kwargs['text'], str):
            self.text = kwargs['text']
        if 'title' in kwargs and isinstance(kwargs['title'], str):
            self.title = kwargs['title']
        if 'type' in kwargs and isinstance(kwargs['type'], str):
            self.type = kwargs['type']
            if self.type not in valid_message_types:
                raise ValueError('Invalid Teams message type provided: {t}'.format(t=self.type))
        if 'level' in kwargs and isinstance(kwargs['level'], str):
            self.level = kwargs['level']
            if self.level not in valid_message_levels:
                raise ValueError('Invalid log level type provided: {t}'.format(t=self.level))
            self.text = get_emoji(self.level) + ' ' + self.text if self.text else None

    def __str__(self):
        return self.payload.__str__()
    
    def add_code_block_to_card(self, code_snippet, language='PlainText'):
        """Add a code block to the card body item list
        
        :param code_snippet: (str) Code snippet to include in the card body item
        :param language: (str) Language of the code snippet
        """
        body_item = {
            'type': 'CodeBlock',
            'codeSnippet': code_snippet,
            'language': language
        }
        self.card_body_items.append(body_item)
    
    def add_danger_text_block_to_card(self, message_text):
        """Add a danger text block to the card body item list
        
        :param message_text: (str) Text to include in the card body item
        """
        msg = get_emoji('error') + ' ' + message_text
        self.add_text_block_to_card(message_text=msg, color=textblock_colors['danger'])
    
    def add_good_text_block_to_card(self, message_text):
        """Add a good text block to the card body item list
        
        :param message_text: (str) Text to include in the card body item
        """
        msg = get_emoji('success') + ' ' + message_text
        self.add_text_block_to_card(message_text=msg, color=textblock_colors['ok'])
    
    def add_heading_block_to_card(self, heading_text, color=None):
        """Add a heading text block to the card body item list
        
        :param heading_text: (str) Text to include in the card body item
        """
        self.add_text_block_to_card(message_text=heading_text, style='heading', color=color)
    
    def add_info_text_block_to_card(self, message_text):
        """Add a info text block to the card body item list
        
        :param message_text: (str) Text to include in the card body item
        """
        msg = get_emoji('info') + ' ' + message_text
        self.add_text_block_to_card(message_text=msg)

    def add_text_block_to_card(self, message_text, **kwargs):
        """Add a text block to the card body item list
        
        :param message_text: (str) Text to include in the card body item
        """
        body_item = {
            'type': 'TextBlock',
            'text': message_text
        }
        for kwarg in kwargs:
            if isinstance(kwargs[kwarg], str):
                body_item[kwarg] = kwargs[kwarg]
        self.card_body_items.append(body_item)
    
    def add_warning_text_block_to_card(self, message_text):
        """Add a warning text block to the card body item list
        
        :param message_text: (str) Text to include in the card body item
        """
        msg = get_emoji('warning') + ' ' + message_text
        self.add_text_block_to_card(message_text=msg, color=textblock_colors['warning'])
    
    def send(self, message_type=None):
        """Sends a Teams message depending on the type specified
        
        :param message_type: (str) Type of message to send
        """
        if not message_type:
            message_type = self.type
        if message_type == 'card':
            if len(self.card_body_items) > 0:
                self.send_card()
            else:
                self.send_simple_card()
        elif message_type == 'code':
            self.send_code_block()
        elif message_type == 'text':
            self.send_message()
        elif len(self.card_body_items) > 0:
            self.send_card()
        else:
            raise Cons3rtTeamsError('Unrecognized Teams message type: {t}'.format(t=message_type))
    
    def send_card(self):
        """Sends the card message using the provided card items added 
        to the card body item list
        
        :return: None
        """
        # Ensure card body items were added
        if len(self.card_body_items) < 1:
            raise Cons3rtTeamsError('No card body items provided for the Teams card message')
        
        # Build the card payload
        self.payload = deepcopy(card_template)
        self.payload['attachments'][0]['content']['body'] = self.card_body_items
        post_teams_webhook(payload=self.payload, webhook_url=self.webhook_url)
    
    def send_code_block(self):
        """
        Sends a code block message
        """
        post_code_block(message=self.text, webhook_url=self.webhook_url)

    def send_message(self):
        """Sends the Teams message

        :return: None
        """
        if not self.text:
            raise Cons3rtTeamsError('No text provided for the Teams message')
        post_text(message=self.text, webhook_url=self.webhook_url)
    
    def send_message_boom(self):
        """Sends the Teams message with the boom emoji

        :return: None
        """
        if not self.text:
            raise Cons3rtTeamsError('No text provided for the Teams message')
        msg = get_emoji('boom') + ' ' + self.text
        post_text(message=msg, webhook_url=self.webhook_url)

    def send_message_error(self):
        """Sends the Teams message with the error emoji

        :return: None
        """
        if not self.text:
            raise Cons3rtTeamsError('No text provided for the Teams message')
        msg = get_emoji('error') + ' ' + self.text
        post_text(message=msg, webhook_url=self.webhook_url)
    
    def send_message_info(self):
        """Sends the Teams message with the info emoji

        :return: None
        """
        if not self.text:
            raise Cons3rtTeamsError('No text provided for the Teams message')
        msg = get_emoji('info') + ' ' + self.text
        post_text(message=msg, webhook_url=self.webhook_url)
    
    def send_message_success(self):
        """Sends the Teams message with the success emoji

        :return: None
        """
        if not self.text:
            raise Cons3rtTeamsError('No text provided for the Teams message')
        msg = get_emoji('success') + ' ' + self.text
        post_text(message=msg, webhook_url=self.webhook_url)
    
    def send_message_warning(self):
        """Sends the Teams message with the warning emoji

        :return: None
        """
        if not self.text:
            raise Cons3rtTeamsError('No text provided for the Teams message')
        msg = get_emoji('warning') + ' ' + self.text
        post_text(message=msg, webhook_url=self.webhook_url)
    
    def send_simple_card(self):
        """Sends a simple card message using the provided text and title

        :return: None
        """
        if not all([self.text, self.title]):
            raise Cons3rtTeamsError('No text or title provided for the Teams card message')
        post_card(title=self.title, content=self.text, webhook_url=self.webhook_url)


class Cons3rtTeamsMessage(TeamsMessage):

    def __init__(self, webhook_url=None):
        self.cls_logger = mod_logger + '.Cons3rtTeamsMessage'
        self.webhook_url = webhook_url
        self.dep = Deployment()
        # If wenbook URL not provided in initialization, check for the deployment prop TEAMS_HOOK
        if not self.webhook_url:
            self.webhook_url = self.dep.get_value('TEAMS_HOOK')
        # If webhook URL not provided in deployment prop, check for the environment variable
        if not self.webhook_url:
            self.webhook_url = teams_hook_env_var
        self.deployment_run_name = self.dep.get_value('cons3rt.deploymentRun.name')
        self.deployment_run_id = self.dep.get_value('cons3rt.deploymentRun.id')

        # Build the message text
        self.message_text = 'Run: ' + self.deployment_run_name + ' (ID: ' + self.deployment_run_id + ')' + '\nHost: *' + \
                          self.dep.cons3rt_role_name + '*'

        # Initialize the TeamsMessage
        try:
            TeamsMessage.__init__(self, webhook_url=self.webhook_url, text=self.message_text)
            self.add_heading_block_to_card(self.message_text)
        except ValueError:
            raise

    def send_cons3rt_agent_logs(self):
        """Sends a Teams message with an attachment for each cons3rt agent log

        :return:
        """
        log = logging.getLogger(self.cls_logger + '.send_cons3rt_agent_logs')

        log.debug('Searching for log files in directory: {d}'.format(d=self.dep.cons3rt_agent_log_dir))
        for item in os.listdir(self.dep.cons3rt_agent_log_dir):
            item_path = os.path.join(self.dep.cons3rt_agent_log_dir, item)
            if os.path.isfile(item_path):
                log.debug('Adding Code block item with cons3rt agent log file: {f}'.format(f=item_path))
                try:
                    with open(item_path, 'r') as f:
                        file_text = f.read()
                except (IOError, OSError) as exc:
                    log.warning('There was a problem opening file: {f}\n{e}'.format(f=item_path, e=str(exc)))
                    continue

                # Take the last 7000 characters
                file_text_trimmed = file_text[-7000:]

                # Add log file name and trimmed content
                self.add_text_block_to_card(message_text=item)
                self.add_code_block_to_card(code_snippet=file_text_trimmed)
        self.send()
    
    def send_text_file(self, text_file):
        """Sends a Teams message with the contents of a text file

        :param: test_file: (str) Full path to text file to send
        :return: None
        :raises: Cons3rtTeamsError
        """
        log = logging.getLogger(self.cls_logger + '.send_text_file')

        # Ensure the file exists
        if not isinstance(text_file, str):
            msg = 'arg text_file must be a string, found type: {t}'.format(t=text_file.__class__.__name__)
            raise Cons3rtTeamsError(msg)
        if not os.path.isfile(text_file):
            msg = 'The provided text_file was not found or is not a file: {f}'.format(f=text_file)
            raise Cons3rtTeamsError(msg)

        # Read the file contents
        try:
            with open(text_file, 'r') as f:
                file_text = f.read()
        except (IOError, OSError) as exc:
            msg = 'There was a problem opening file: {f}'.format(f=text_file)
            raise Cons3rtTeamsError(msg) from exc

        # Take the last 7000 characters
        log.debug('Attempting to send a Teams message with the contents of file: {f}'.format(f=text_file))
        file_text_trimmed = file_text[-7000:]
        # Add log file name and trimmed content
        self.add_text_block_to_card(message_text=text_file)
        self.add_code_block_to_card(code_snippet=file_text_trimmed)
        self.send()


def get_emoji(name):
    try:
        return emoji[name]
    except:
        return "bad emoji reference"


def post_card(title, content, webhook_url=None):
    
    log = logging.getLogger(mod_logger + '.post_card')
    log.debug(f'Posting Teams card with title: {title}')
    log.debug(f'Posting Teams card with content: {content}')
    payload = {
        "type":"message",
        "attachments":[{
            "contentType":"application/vnd.microsoft.card.adaptive",
            "content":{
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.5",
                "body":[
                    {
                        "type": "TextBlock",
                        "text": f"{title}",
                        "style": "heading"
                    },
                    {
                        "type": "CodeBlock",
                        "codeSnippet": f"{content}",
                        "language": "PlainText"
                    }
                ]
            }
        }]
    }
    post_teams_webhook(payload=payload, webhook_url=webhook_url)


def post_code_block(message, webhook_url=None):
    """
    Post a simple code block to the Teams webhook URL
    
    :param message: (str) The content of the code block
    :param webhook_url: (str) Teams webhook URL
    :return: None
    """
    payload = {
        'type': 'text',
        'text': '<pre>{m}</pre>'.format(m=message)
    }
    post_teams_webhook(payload=payload, webhook_url=webhook_url)


def post_teams_webhook(payload, webhook_url=None):
    """
    Post the provided payload to the Teams webbook URL as JSON
    
    :param payload: (dict) The payload to post to the Teams webhook
    :param webhook_url: (str) The Teams webhook URL to post the payload to
    :return: None
    :raises OSError: If there is a problem encoding the JSON payload or posting to the
    """
    log = logging.getLogger(mod_logger + '.post_teams_webhook')

    # Set headers
    headers = {"Content-Type": "application/json"}

    # Use the provided webbhook URL or fallback to the environment variable
    if not webhook_url:
        webhook_url = teams_hook_env_var
    
    # Encode payload in JSON
    log.debug('Using payload: %s', payload)
    try:
        json_payload = json.JSONEncoder().encode(payload)
    except(TypeError, ValueError, OverflowError) as exc:
        msg = 'There was a problem encoding the JSON payload'
        raise OSError(msg) from exc

    # Post the provided data to the Teams webhook URL
    log.debug('Posting data to Teams webhook URL [{u}]:\n[{d}]'.format(
        u=webhook_url, d=str(payload)))
    try:
        result = requests.post(url=webhook_url, headers=headers, data=json_payload)
    except requests.exceptions.ConnectionError as exc:
        msg = 'There was a problem posting to Teams'
        raise OSError(msg) from exc

    # Check return code
    if result.status_code not in [200, 202]:
        log.error('Post to Teams webhook url [{u}] failed with code: [{c}] and content:\n[{d}]'.format(
            c=result.status_code, u=webhook_url, d=str(result.content)))
    else:
        log.debug('Posted to Teams successfully.')



def post_text(message, webhook_url=None):
    """
    Post a simple text message to the Teams webhook URL
    
    :param message: (str) The text of the message
    :param webhook_url: (str) Teams webhook URL
    :return: None
    """
    payload = {
        'type': 'text',
        'text': message
    }
    post_teams_webhook(payload=payload, webhook_url=webhook_url)


def main():
    """Handles external calling for this module

    Execute this python module and provide the args shown below to
    external call this module to send Teams messages!

    :return: None
    """
    log = logging.getLogger(mod_logger + '.main')
    parser = argparse.ArgumentParser(description='Sending Teams messages.')
    parser.add_argument('-l', '--level', help='Log level of the Teams post', required=False)
    parser.add_argument('-t', '--text', help='Text of the message', required=True)
    parser.add_argument('--title', help='Title of the Teams Card', required=False)
    parser.add_argument('--type', 
                        help='Type of Teams message [{t}]'.format(t=','.join(valid_message_types)), 
                        required=False
                        )
    parser.add_argument('-u', '--url', help='Teams webhook URL', required=False)
    args = parser.parse_args()

    # Determine the teams webhook URL to use
    if args.url:
        teams_hook_url = args.url
    elif teams_hook_env_var:
        teams_hook_url = teams_hook_env_var
    else:
        log.error('No Teams webhook URL provided or found in TEAMS_HOOK env var')
        return 3
    
    # Determine the message type
    if args.type:
        if not args.type in valid_message_types:
            log.error('Invalid Teams message type provided [{t}], must be one of: [{v}]'.format(
                t=args.type, v=','.join(valid_message_types)))
            return 4
        message_type = args.type
    else:
        message_type = 'text'
    
    # Determine the log level
    message_level = None
    if args.level:
        if not args.level in valid_message_levels:
            log.error('Invalid Teams message level provided [{l}], must be one of: [{v}]'.format(
                l=args.level, v=','.join(valid_message_levels)))
            return 5
        message_level = args.level

    # Create the TeamsMessage object
    try:
        teams_msg = TeamsMessage(teams_hook_url, text=args.text, title=args.title, type=message_type, level=message_level)
    except ValueError as exc:
        msg = 'Unable to create Teams message\n{e}\n{t}'.format(e=str(exc), t=traceback.format_exc())
        log.error(msg)
        return 1

    # Send Teams message
    try:
        teams_msg.send()
    except(TypeError, ValueError, IOError) as exc:
        log.error('Unable to send Teams message\n{e}'.format(e=str(exc)))
        return 2
    log.debug('Your Teams message has been sent successfully!')
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
