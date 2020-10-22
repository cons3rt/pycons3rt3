import json
import logging
import sys

import requests
from requests.exceptions import RequestException
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError, MailChimpListerError
from pycons3rt3.logify import Logify
from pycons3rt3.slack import SlackAttachment, SlackMessage


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.mailchimp'


class MailChimpLister(object):

    def __init__(self, site_name, mailchimp_rest_url, list_id, api_key, slack_url, slack_channel, config_file=None):
        self.cls_logger = mod_logger + '.MailChimpLister'
        self.slack_msg = SlackMessage(
            slack_url,
            channel=slack_channel,
            text='Mail Chimp List Sync Util: {n}'.format(n=site_name)
        )
        self.mailchimp_rest_url = mailchimp_rest_url
        self.list_id = list_id
        self.api_key = api_key
        self.config_file = config_file
        self.site_user_list = []
        self.list_members = []
        self.add_count = 0
        self.add_fail_count = 0
        self.update_count = 0
        self.update_tags_count = 0
        self.no_updated_needed_count = 0
        self.update_fail_count = 0
        self.do_slack = True

    def post_to_slack(self, msg, error=False):
        """Posts mailchimp list updates to Slack

        :param msg: (str) message
        :param error: (bool) True sends an error Slack post
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.post_to_slack')
        if not self.do_slack:
            log.info('Slack posting set to: FALSE')
            return
        if error:
            color = 'danger'
        else:
            color = 'good'
        attachment = SlackAttachment(fallback=msg, text=msg, color=color)
        self.slack_msg.add_attachment(attachment=attachment)
        try:
            self.slack_msg.send()
        except OSError:
            _, ex, trace = sys.exc_info()
            log.warning('Unable to post Slack message: {m}\n{e}'.format(m=msg, e=str(ex)))

    def get_cons3rt_users(self):
        """Query the site for all users

        :return: None
        :raises: MailChimpListerError
        """
        log = logging.getLogger(self.cls_logger + '.get_users')

        # Create a Cons3rtApi
        rest_client = Cons3rtApi(config_file=self.config_file)

        # Query the site for all users
        log.info('Attempting to query site for all users...')
        try:
            user_list = rest_client.retrieve_all_users()
        except Cons3rtApiError as exc:
            raise MailChimpListerError('There was a problem retrieving the list of users from CONS3RT') from exc

        # Ensure a list was returned
        if not isinstance(user_list, list):
            raise MailChimpListerError('Expected a list, but CONS3RT returned type: {t}'.format(
                t=user_list.__class__.__name__))
        self.site_user_list = user_list

    def get_list_members(self):
        """Retrieves the list of members on a MailChimp List

        :return: None
        :raises: MailChimpListerError
        """
        log = logging.getLogger(self.cls_logger + '.get_list_members')

        headers = {
            'Authorization': 'apikey {k}'.format(k=self.api_key),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        # Query the list to get the number of users
        url = self.mailchimp_rest_url + 'lists/{i}'.format(i=self.list_id)
        log.info('Attempting to query MailChimp for stats on list ID: {i}'.format(i=self.list_id))
        try:
            response = requests.get(url, headers=headers)
        except RequestException as exc:
            raise MailChimpListerError('There was a problem querying the MailChimp API for list: {i}'.format(
                i=self.list_id)) from exc

        decoded_content = decode_http_content_response(response.content)

        # Check the status code
        if response.status_code == requests.codes.ok:
            list_data_json = decoded_content
            log.info('Successfully retrieved stats for list ID: {i}'.format(i=self.list_id))
        else:
            raise MailChimpListerError('MailChimp API returned code {o} with content:\n{c}'.format(
                o=str(response.status_code), c=decoded_content))

        # Load the JSON data
        list_data = json.loads(list_data_json)

        # Try to get the number of members in the list
        default_member_count = 3000
        try:
            subscribed_count_data = list_data['stats']['member_count']
            subscribed_count = int(subscribed_count_data)
            unsubscribed_count_data = list_data['stats']['unsubscribe_count']
            unsubscribed_count = int(unsubscribed_count_data)
            cleaned_count_data = list_data['stats']['cleaned_count']
            cleaned_count = int(cleaned_count_data)
            member_count = subscribed_count + unsubscribed_count + cleaned_count
        except (KeyError, TypeError) as exc:
            msg = 'Unable to determine member count, using default member count [{d}]\n{e}'.format(
                d=str(default_member_count), e=str(exc))
            member_count = default_member_count
            log.error(msg)
        else:
            log.info('Found list ID [{i}] member count: {n}'.format(n=str(member_count), i=self.list_id))

        # Using a max of 1000, query mailchimp for a list of members to add
        offset = 0
        count = 1000
        while True:
            log.info('Attempting to retrieve {c} members with offset: {o}'.format(c=str(count), o=str(offset)))
            retrieved_members = self.retrieve_list_members(count=count, offset=offset)
            if retrieved_members < count:
                log.info('Retrieved members {n} is < {c}, looks like we got them all'.format(
                    n=str(retrieved_members), c=str(count)))
                break
            else:
                offset += count
                log.info('Querying again with offset set to: {o}'.format(o=str(offset)))

        # Ensure the list of members built matches the expected amount
        if len(self.list_members) != member_count:
            raise MailChimpListerError('Expected [{e}] list members but only found: {a}'.format(
                e=str(member_count), a=str(len(self.list_members))))
        else:
            log.info('Built a list of [{c}] members, which is the expected number'.format(
                c=str(len(self.list_members))))

    def retrieve_list_members(self, count=1000, offset=0):
        """Queries MailChimp for members, and adds them to a list

        :param count: (int) number of members to query
        :param offset: (int) number of members to skip when iterating
        :return: None
        :raises: MailChimpListerError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_list_members')

        headers = {
            'Authorization': 'apikey {k}'.format(k=self.api_key),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        # Query the list members
        url = self.mailchimp_rest_url + 'lists/{i}/members?count={c}&offset={o}'.format(
            i=self.list_id, c=str(count), o=str(offset))

        log.info('Querying MailChimp to retrieve details on [{c}] members with offset [{o}] from List ID {i} '
                 'with query URL: {u}'.format(i=self.list_id, o=str(offset), c=str(count), u=url))
        try:
            response = requests.get(url, headers=headers)
        except RequestException:
            raise MailChimpListerError('There was a problem querying the MailChimp API for the list of users')

        decoded_content = decode_http_content_response(response.content)

        # Check the status code
        if response.status_code == requests.codes.ok:
            list_member_data_json = decoded_content
            log.info('Successfully retrieved details on [{c}] members from list ID: {i}'.format(
                c=str(count), i=self.list_id))
        else:
            raise MailChimpListerError('MailChimp API returned code {o} with content:\n{c}'.format(
                o=str(response.status_code), c=decoded_content))

        # Ensure the type returned
        if not list_member_data_json:
            raise MailChimpListerError('list_member_data_json not returned')
        if not isinstance(list_member_data_json, str):
            raise MailChimpListerError('Expected str, but MailChimp API returned type: {t}'.format(
                t=list_member_data_json.__class__.__name__))

        # Load the JSON data
        list_member_data = json.loads(list_member_data_json)

        # Ensure the type returned
        if not isinstance(list_member_data, dict):
            raise MailChimpListerError('Expected dict, but MailChimp API returned type: {t}'.format(
                t=list_member_data.__class__.__name__))

        # Parse the response
        log.info('Examining returned member data and adding to the list of members...')
        retrieved_member_count = 0
        try:
            for member in list_member_data['members']:
                member_entry = {
                    'id': member['id'],
                    'status': member['status'],
                    'email': member['email_address']
                }
                if 'merge_fields' in member:
                    if 'FNAME' in member['merge_fields']:
                        member_entry['firstname'] = member['merge_fields']['FNAME']
                    else:
                        member_entry['firstname'] = 'None'
                    if 'LNAME' in member['merge_fields']:
                        member_entry['lastname'] = member['merge_fields']['LNAME']
                    else:
                        member_entry['lastname'] = 'None'
                self.list_members.append(member_entry)
                retrieved_member_count += 1
        except KeyError as exc:
            raise MailChimpListerError('There was a problem parsing member data received from MailChimp') from exc
        log.info('Retrieved {n} members'.format(n=str(retrieved_member_count)))
        return retrieved_member_count

    def update_list(self, tag_prefix):
        """Examine the site and list members and update/add users as needed

        :param tag_prefix (str) prefix to apply to site member status tags
        :return: None
        :raises: MailChimpListerError
        """
        log = logging.getLogger(self.cls_logger + '.update_list')

        # Search the list of CONS3RT users
        for user in self.site_user_list:
            user_found = False
            if 'email' not in user:
                log.warning('User does not have an email address: {u}'.format(u=str(user)))
                continue
            if 'state' not in user:
                log.warning('User does not have an state: {u}'.format(u=str(user)))
                continue
            user_email = user['email'].strip().lower()
            log.info('Looking at CONS3RT user with email: {e}'.format(e=user_email))
            if user['state'] == 'ACTIVE':
                user_tag = '{t}_Active'.format(t=tag_prefix)
            elif user['state'] == 'INACTIVE':
                user_tag = '{t}_Inactive'.format(t=tag_prefix)
            elif user['state'] == 'REQUESTED':
                user_tag = '{t}_Requested'.format(t=tag_prefix)
            else:
                user_tag = '{t}_Unknown_State'.format(t=tag_prefix)
            log.info('Set expected tag to be: {t}'.format(t=user_tag))
            if 'hanscom.af.mil' in user_email:
                log.warning('Skipping user with hanscom.af.mil email address: {e}'.format(e=user_email))
                continue
            if 'usace.army.mil' in user_email:
                log.warning('Skipping user with usace.army.mil email address (they have opted out from MailChimp '
                            'and adding to the list errors out: {e}'.format(e=user_email))
                continue
            for member in self.list_members:
                if 'email' not in member:
                    log.warning('Member found with no email address: {m}'.format(m=str(member)))
                    continue
                member_email = member['email'].strip().lower()
                if user_email == member_email:
                    user_found = True
                    log.info('Found existing list member: [{e}]'.format(e=user['email']))
                    self.update_list_member(member=member, user=user)
                    self.update_member_tags(member=member, tag=user_tag)
                    break
            if not user_found:
                log.info('User email not subscribed to MailChimp list, adding email: {e}'.format(e=user['email']))
                self.add_list_member(user=user, tag=user_tag)
        msg = 'List update complete for list ID: {i}\nMembers Added: {a}\nMembers Updated: {u}\nAdd Fails: {af}\n' \
              'Update Fails: {uf}\nUpdates Not Needed: {n}\nTags Updated: {t}'.format(i=self.list_id,
                                                                                      a=self.add_count,
                                                                                      u=self.update_count,
                                                                                      af=self.add_fail_count,
                                                                                      uf=self.update_fail_count,
                                                                                      n=self.no_updated_needed_count,
                                                                                      t=self.update_tags_count)
        log.info(msg)
        self.post_to_slack(msg)

    def add_list_member(self, user, tag):
        """Adds CONS3RT user to the mailchimp list

        :param user: (dict) CONS3RT user data
        :param tag: (str) tag to apply
        :return: None
        :raises: MailChimpListerError
        """
        log = logging.getLogger(self.cls_logger + '.add_list_member')
        log.debug('Adding user: {m}'.format(m=user))
        url = self.mailchimp_rest_url + 'lists/{i}/members'.format(i=self.list_id)
        headers = {
            'Authorization': 'apikey {k}'.format(k=self.api_key),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        content = {
            'email_address': user['email'],
            'status': 'subscribed',
            'merge_fields': {
                'FNAME': user['firstname'],
                'LNAME': user['lastname']
            },
            'tags': [tag]
        }

        # Encode the content in JSON
        json_content = json.dumps(content)

        # Add the user using the MailChimp API
        log.debug('Adding user with email {e} to list ID: {i}'.format(i=self.list_id, e=user['email']))
        try:
            response = requests.post(url, headers=headers, data=json_content)
        except RequestException as exc:
            msg = 'There was a problem querying the MailChimp API to add member with email: {m}\n{e}'.format(
                m=user['email'], e=str(exc))
            log.error(msg)
            self.add_fail_count += 1
            self.post_to_slack(msg, error=True)
            return

        decoded_content = decode_http_content_response(response.content)

        # Check the status code
        if response.status_code == requests.codes.ok:
            self.add_count += 1
            msg = 'User with email [{e}] and tag [{t}] successfully added to MailChimp List ID: {i}'.format(
                e=user['email'], t=tag, i=self.list_id)
            log.info(msg)
            self.post_to_slack(msg)
        else:
            msg = 'Unable to add user with email {m}, MailChimp API returned code {o} with content:\n{c}'.format(
                m=user['email'], o=str(response.status_code), c=decoded_content)
            log.error(msg)
            self.add_fail_count += 1
            self.post_to_slack(msg, error=True)

    def get_list_member_details(self, member):
        """Returns details for the list member

        :param member: (dict) member data returned from the lists/members API call
        :return: (dict) member detail data
        """
        log = logging.getLogger(self.cls_logger + '.get_list_member_details')

        log.info('Attempting to query details for list member with email [{e}] and ID [{i}]'.format(
            e=member['email'], i=member['id']))

        url = self.mailchimp_rest_url + 'lists/{i}/members/{m}'.format(i=self.list_id, m=member['id'])
        headers = {
            'Authorization': 'apikey {k}'.format(k=self.api_key),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        # Attempt to update the member info
        try:
            response = requests.get(url, headers=headers)
        except RequestException as exc:
            msg = 'There was a problem querying the MailChimp API to get member details' \
                  'email: {m}\n{e}'.format(m=member['email'], e=str(exc))
            log.error(msg)
            self.post_to_slack(msg, error=True)
            return

        decoded_content = decode_http_content_response(response.content)

        # Check the status code
        if response.status_code != requests.codes.ok:
            msg = 'There was a problem querying details for member with email {m}, MailChimp API returned code {o} ' \
                  'with content:\n{c}'.format(m=member['email'], o=str(response.status_code), c=decoded_content)
            log.error(msg)
            self.post_to_slack(msg, error=True)
            return

        # Return the member details
        member_details_json = decoded_content
        member_details = json.loads(member_details_json)
        log.debug('Found member details: {d}'.format(d=str(member_details)))
        return member_details

    def update_list_member(self, member, user):
        """Updates an existing List member first/last names if not provided

        :param member: (dict) member data
        :param user:  (dict) CONS3RY user data
        :return: None
        :raises: MailChimpListerError
        """
        log = logging.getLogger(self.cls_logger + '.update_list_member')
        log.debug('Attempting to update list member: {m}'.format(m=str(member)))
        update_member = False
        content = {}
        try:
            member_firstname = member['firstname'].strip()
            member_lastname = member['lastname'].strip()
            user_firstname = user['firstname'].strip()
            user_lastname = user['lastname'].strip()
            if member_firstname != user_firstname:
                update_member = True
                content['merge_fields'] = {}
                content['merge_fields']['FNAME'] = user['firstname']
            if member_lastname != user_lastname:
                update_member = True
                if 'merge_fields' not in content:
                    content['merge_fields'] = {}
                content['merge_fields']['LNAME'] = user['lastname']
        except KeyError as exc:
            raise MailChimpListerError('Problem looking for First/Last name updates') from exc

        # Update the list member only if needed
        if update_member:
            log.info('Attempting to update member ID: {m}'.format(m=member['id']))
            url = self.mailchimp_rest_url + 'lists/{i}/members/{m}'.format(i=self.list_id, m=member['id'])
            headers = {
                'Authorization': 'apikey {k}'.format(k=self.api_key),
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }

            # Encode the content in JSON
            json_content = json.dumps(content)

            # Attempt to update the member info
            try:
                response = requests.patch(url, headers=headers, data=json_content)
            except RequestException as exc:
                msg = 'Problem querying the MailChimp API to update member with email: {m}\n{e}'.format(
                    m=user['email'], e=str(exc))
                log.error(msg)
                self.update_fail_count += 1
                self.post_to_slack(msg, error=True)
                return

            decoded_content = decode_http_content_response(response.content)

            # Check the status code
            if response.status_code == requests.codes.ok:
                msg = 'User with email {e} successfully updated in MailChimp List ID: {i}'.format(
                    e=user['email'], i=self.list_id)
                log.info(msg)
                self.update_count += 1
                # self.post_to_slack(msg)
            else:
                msg = 'There was a problem updating member with email {m}, MailChimp API returned code {o} with ' \
                      'content:\n{c}'.format(m=user['email'], o=str(response.status_code), c=decoded_content)
                log.error(msg)
                self.update_fail_count += 1
                self.post_to_slack(msg, error=True)
        else:
            self.no_updated_needed_count += 1
            log.debug('No need to update user with email: {e}'.format(e=user['email']))

    def determine_update_tags(self, member, tag):
        """Updates an existing list member tags

        :param member: (dict) member data
        :param tag: (str) tag to apply to the user
        :return: None or (dict) containing tags
        """
        log = logging.getLogger(self.cls_logger + '.determine_update_tags')

        # Check if the tags need to be updated
        new_tags = [
            {
                'name': tag,
                'status': 'active'
            }
        ]

        # Query the list member for tags
        member_details = self.get_list_member_details(member=member)
        if not member_details:
            log.warning('Unable to get member details to update tags for member: {m}'.format(m=member['email']))
            return

        if 'tags' not in member_details:
            log.info('No tags found for member [{m}] tag will be added: [{t}]'.format(t=tag, m=member['email']))
            return new_tags

        if not isinstance(member_details['tags'], list):
            log.warning('member tags are not a list, found: {t}'.format(t=member_details['tags'].__class__.__name__))
            return

        if len(member_details['tags']) == 0:
            log.info('No tags found, the new tag will be added')
            return new_tags

        # Process tags on the member
        log.info('Found member [{m}] tags: {t}'.format(m=member['email'], t=str(member_details['tags'])))

        for member_tag in member_details['tags']:
            if 'name' in member_tag:
                if member_tag['name'] == tag:
                    log.info('Tag [{t}] already exists on list member: {m}'.format(t=tag, m=member['email']))
                    return
                elif member_tag['name'].endswith('Active') or \
                        member_tag['name'].endswith('Inactive') or \
                        member_tag['name'].endswith('Requested'):
                    log.info('Tag will be removed: {t}'.format(t=member_tag['name']))
                    new_tags.append({
                        'name': member_tag['name'],
                        'status': 'inactive'
                    })
                else:
                    log.info('Keeping existing tag: {t}'.format(t=member_tag['name']))
                    new_tags.append({
                        'name': member_tag['name'],
                        'status': 'active'
                    })
        log.info('New tags for user [{m}], will be set to: {t}'.format(t=str(new_tags), m=member['email']))
        return new_tags

    def update_member_tags(self, member, tag):
        """Updates an existing list member tags

        :param member: (dict) member data
        :param tag: (str) desired tag to apply to the list member
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.update_member_tags')

        new_tags = self.determine_update_tags(member=member, tag=tag)

        if not new_tags:
            log.info('Tags do not need updating for member: [{m}]'.format(m=member['email']))
            return

        # Update tags on the member
        log.info('Attempting to update tags for member ID {m} with: {t}'.format(
            m=member['id'], t=str(new_tags)))
        url = self.mailchimp_rest_url + 'lists/{i}/members/{m}/tags'.format(i=self.list_id, m=member['id'])
        headers = {
            'Authorization': 'apikey {k}'.format(k=self.api_key),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        content = {
            'tags': new_tags
        }
        json_content = json.dumps(content)
        log.debug('Using JSON content: ')
        try:
            response = requests.post(url, headers=headers, data=json_content)
        except RequestException:
            _, ex, trace = sys.exc_info()
            msg = '{n}: There was a problem querying the MailChimp API to update member ' \
                  '[{m}] with tags [{t}]\n{e}'.format(n=ex.__class__.__name__,
                                                      m=member['email'],
                                                      t=str(new_tags), e=str(ex))
            log.error(msg)
            self.update_fail_count += 1
            self.post_to_slack(msg, error=True)
            return

        decoded_content = decode_http_content_response(response.content)

        # Check the status code
        if 200 <= response.status_code < 300:
            self.update_tags_count += 1
            # msg = 'Updated tags for member [{m}]: [{t}] '.format(t=str(new_tags), m=member['email'])
            # self.post_to_slack(msg)
        else:
            msg = 'There was a problem updating member with email {m} with tags [{t}], MailChimp API ' \
                  'returned code {o} with content:\n{c}'.format(m=member['email'],
                                                                o=str(response.status_code),
                                                                t=str(new_tags),
                                                                c=decoded_content)
            log.error(msg)
            self.update_fail_count += 1
            self.post_to_slack(msg, error=True)


def decode_http_content_response(content):
    log = logging.getLogger(mod_logger + '.decode_http_content_response')
    # Determine is there is content and if it needs to be decoded
    decoded_content = None
    if content:
        log.debug('Parsing response with content: {s}'.format(s=content))
        if isinstance(content, bytes):
            log.debug('Decoding bytes: {b}'.format(b=content))
            decoded_content = content.decode('utf-8')
        else:
            decoded_content = content
    return decoded_content
