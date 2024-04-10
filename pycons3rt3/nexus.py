#!/usr/bin/python

"""Module: nexus

This module provides simple method of fetching artifacts from a nexus
repository.

"""

import argparse
import json
import logging
import os
import sys
import traceback

from requests.auth import HTTPBasicAuth
from netrc import netrc, NetrcParseError

from .exceptions import Cons3rtClientError
from .logify import Logify
from .httpclient import http_download, http_get_with_retries, parse_response

__author__ = 'Joe Yennaco'

mod_logger = Logify.get_name() + '.nexus'

# Default max retry attempts for the query
default_max_retry_attempts = 10

# Default retry time in seconds
default_retry_time_sec = 3

# Default timeout for downloads
default_download_timeout_sec = 600


def print_items(item_list):
    """Prints a list of items to stdout

    :param item_list: (list) of items
    :return: None
    """
    for item in item_list:
        print(json.dumps(item))
    print('Returned [{n}] items'.format(n=str(len(item_list))))


def search_cli(base_url, repository, group=None, name=None, extension=None, sort_type=None, direction=None,
               version=None, classifier=None, latest=False, username=None, password=None):
    """Handles the 'search' CLI command

    :param base_url: (str) Nexus base URL
    :param repository: (str) name of the repository to search
    :param group: (str) optional group name
    :param name: (str) optional artifact name
    :param extension: (str) optional extension for the file being searched
    :param sort_type: (str) sort type:
        version - gets the latest version sorted to the top
        group
        name
        repository
    :param direction (str) Sort direction (asc or desc)
    :param version (str) optional artifact version
    :param classifier: (str) optional classifier to filter search results
    :param latest (bool) Set true to return the latest version of an artifacts from a search
    :param username: (str) username
    :param password: (str) password
    :return: (list) of items (dict)
    :raises: RuntimeError
    """
    log = logging.getLogger(mod_logger + '.search_cli')
    if latest:
        log.info('Searching for the latest artifact...')
        result = search_latest(
            base_url=base_url,
            repository=repository,
            group=group,
            name=name,
            extension=extension,
            username=username,
            password=password
        )
        print_items([result])
    else:
        log.info('Searching for artifacts...')
        search_results = search_nexus_assets(
            base_url=base_url,
            repository=repository,
            group=group,
            name=name,
            extension=extension,
            sort_type=sort_type,
            direction=direction,
            version=version,
            classifier=classifier,
            username=username,
            password=password
        )
        print_items(search_results)


def search_latest(base_url, repository, group=None, name=None, extension=None, classifier=None, username=None,
                  password=None):
    """Return 1 search result containing the latest artifact version meeting the provided query parameters

    :param base_url: (str) Nexus base URL
    :param repository: (str) name of the repository to search
    :param group: (str) optional group name
    :param name: (str) optional artifact name
    :param extension: (str) optional extension for the file being searched
    :param classifier: (str) optional classifier to filter search results
    :param username: (str) username
    :param password: (str) password
    :return: (dict) latest search result or None
    :raises: RuntimeError
    """
    log = logging.getLogger(mod_logger + '.search_latest')
    msg = 'Searching for the latest artifact in [{u}]'.format(u=base_url)
    if repository:
        msg += ', in repository [{r}]'.format(r=repository)
    if group:
        msg += ', for group [{g}]'.format(g=group)
    if name:
        msg += ', for name [{n}]'.format(n=name)
    log.info(msg)
    search_results = search_nexus_assets(
        base_url=base_url,
        repository=repository,
        group=group,
        name=name,
        extension=extension,
        sort_type='version',
        classifier=classifier,
        username=username,
        password=password
    )
    if len(search_results) >= 1:
        log.info('Returning the latest version')
        return search_results[0]
    log.info('No search results to return')


def search_nexus_assets(base_url, repository, group=None, name=None, extension=None, sort_type=None, direction=None,
                        version=None, classifier=None, username=None, password=None, continuation_token=None):
    """Search the Nexus Search API for assets

    :param base_url: (str) Nexus base URL
    :param repository: (str) name of the repository to search
    :param group: (str) optional group name
    :param name: (str) optional artifact name
    :param extension: (str) optional extension for the file being searched
    :param sort_type: (str) sort type:
        version - gets the latest version sorted to the top
        group
        name
        repository
    :param direction (str) Sort direction (asc or desc)
    :param version (str) optional artifact version
    :param classifier: (str) optional classifier to filter search results
    :param username: (str) username
    :param password: (str) password
    :param continuation_token: (str) continuation token to retrieve additional results
    :return: (list) of items (dict)
    :raises: RuntimeError
    """
    log = logging.getLogger(mod_logger + '.search_nexus_assets')

    # Store the artifact list
    artifact_list = []

    # Set the target URL
    target = base_url + '/service/rest/v1/search/assets?repository={r}'.format(r=repository)

    # Determine the auth based on username and password
    basic_auth = None
    if all([username, password]):
        log.info('Using the provided username/password for basic authentication...')
        basic_auth = HTTPBasicAuth(username, password)
    else:
        log.info('Not using authentication to Nexus')

    # Determine the headers
    headers = {
        'accept': 'application/json'
    }

    # Check for a various search params and add to the query string
    if group:
        target += '&group=' + group
    if name:
        target += '&name=' + name
    if extension:
        target += '&maven.extension=' + extension
    if classifier:
        target += '&maven.classifier=' + classifier
    if sort_type:
        target += '&sort=' + sort_type
        if direction:
            target += '&direction=' + direction  # only relevant with sort_type
    if version:
        target += '&version=' + version
    if continuation_token:
        target += '&continuationToken=' + continuation_token

    # Make the http GET request
    log.info('Query target: ' + target)
    try:
        response = http_get_with_retries(url=target, headers=headers, basic_auth=basic_auth)
    except Cons3rtClientError as exc:
        msg = 'Error encountered querying URL [{u}]\n{e}'.format(u=target, e=str(exc))
        raise RuntimeError(msg) from exc

    # Parse the response
    content = parse_response(response=response)
    search_result = json.loads(content)

    # Add results to the list
    item_count = 0
    if 'items' in search_result.keys():
        if isinstance(search_result['items'], list):
            for item in search_result['items']:
                if isinstance(item, dict):
                    artifact_list.append(item)
                    item_count += 1
    log.info('Added [{n}] items to the search results'.format(n=str(item_count)))

    # Determine if there was a continuation token
    continuation_token = None
    if 'continuationToken' in search_result.keys():
        if search_result['continuationToken']:
            continuation_token = search_result['continuationToken']
    if continuation_token:
        log.info('Searching for more artifacts with continuation token: {t}'.format(t=continuation_token))
        try:
            artifact_list += search_nexus_assets(
                base_url=base_url,
                repository=repository,
                group=group,
                name=name,
                extension=extension,
                sort_type=sort_type,
                direction=direction,
                version=version,
                classifier=classifier,
                username=username,
                password=password,
                continuation_token=continuation_token)
        except RuntimeError as exc:
            msg = 'Error searching for artifacts with continuation token [{t}]\n{e}'.format(
                t=continuation_token, e=str(exc))
            raise RuntimeError(msg) from exc
    return artifact_list


def get_artifact_nexus(base_url, repository, group_id, artifact_id, packaging, destination_dir, version=None,
                       classifier=None, suppress_status=False, timeout_sec=default_download_timeout_sec,
                       retry_sec=default_retry_time_sec, max_retries=default_max_retry_attempts, overwrite=True,
                       username=None, password=None):
    """Retrieves an artifact from the Nexus 3 ReST API

    :param suppress_status: (bool) Set to True to suppress printing download status
    :param base_url: (str) Base URL of the Nexus Server (domain name portion only, see sample)
    :param repository: (str) Repository to query (e.g. snapshots, releases)
    :param group_id: (str) The artifact's Group ID in Nexus
    :param artifact_id: (str) The artifact's Artifact ID in Nexus
    :param packaging: (str) The artifact's packaging (e.g. war, zip)
    :param destination_dir: (str) Full path to the destination directory
    :param version: (str) optional version of the artifact, when not set, retrieve the latest
    :param classifier: (str) optional classifier to filter search results
    :param timeout_sec: (int) Number of seconds to wait before timing out the artifact retrieval
    :param retry_sec: (int) Number of seconds in between retry attempts
    :param max_retries: (int) Maximum number of retries
    :param overwrite: (bool) True overwrites the file on the local system if it exists,
    :param username: (str) username for basic auth
    :param password: (str) password for basic auth
    :return: (str) Downloaded artifact path
    :raises: TypeError, ValueError, OSError, RuntimeError
    """
    log = logging.getLogger(mod_logger + '.get_artifact_nexus')
    log.info('Using Nexus Server URL: {u}'.format(u=base_url))

    if not destination_dir:
        raise RuntimeError('Destination directory is required to download an artifact')

    # Ensure the destination directory exists
    if not os.path.isdir(destination_dir):
        log.info('Specified destination_dir not found on file system, creating: {d}'.format(d=destination_dir))
        try:
            os.makedirs(name=destination_dir, exist_ok=True)
        except (OSError, IOError) as exc:
            raise OSError('[{n}] creating destination directory: {d}\n{e}'.format(
                n=type(exc).__name__, d=destination_dir, e=str(exc)))

    # Determine the auth based on username and password
    basic_auth = None
    if all([username, password]):
        log.info('Using the provided username/password for basic authentication...')
        basic_auth = HTTPBasicAuth(username, password)
    else:
        log.info('Not using authentication to Nexus')

    if version:
        log.info('Searching for artifacts...')
        search_results = search_nexus_assets(
            base_url=base_url,
            repository=repository,
            group=group_id,
            name=artifact_id,
            extension=packaging,
            version=version,
            classifier=classifier,
            username=username,
            password=password
        )
    else:
        log.info('Searching for the latest artifact...')
        search_results = search_latest(
            base_url=base_url,
            repository=repository,
            group=group_id,
            name=artifact_id,
            extension=packaging,
            classifier=classifier,
            username=username,
            password=password
        )

    # Ensure only 1 result was found in the search
    if isinstance(search_results, list):
        if len(search_results) != 1:
            raise RuntimeError('Expected 1 search result, found [{n}]'.format(n=str(len(search_results))))
        artifact_data = search_results[0]
    elif isinstance(search_results, dict):
        artifact_data = search_results
    else:
        raise RuntimeError('Expected a list or dict returned from search, found: [{t}]'.format(
            t=type(search_results).__name__))

    # Get the download URL
    if 'downloadUrl' not in artifact_data.keys():
        raise RuntimeError('downloadUrl not found in data: {d}'.format(d=str(artifact_data)))
    download_url = artifact_data['downloadUrl']
    artifact_file_name = download_url.split('/')[-1]
    download_file = os.path.join(destination_dir, artifact_file_name)

    # If the file exists, either remove it or return
    if os.path.isfile(download_file) and overwrite:
        log.info('File already exists, removing: {d}'.format(d=download_file))
        os.remove(download_file)
    elif os.path.isfile(download_file):
        log.info('File already exists [{d}], and overwrite was not requested, not downloading'.format(d=download_file))
        return download_file

    # Attempt to download the artifact
    log.info('Downloading artifact from URL [{u}] to destination: [{d}]'.format(u=download_url, d=download_file))
    try:
        http_download(url=download_url, download_file=download_file, basic_auth=basic_auth,
                      suppress_status=suppress_status, max_retry_attempts=max_retries, retry_time_sec=retry_sec,
                      timeout_sec=timeout_sec)
    except Cons3rtClientError as exc:
        msg = 'Problem downloading artifact from URL [{u}] to [{d}]\n{e}'.format(
            u=download_url, d=download_file, e=str(exc))
        raise RuntimeError(msg) from exc
    return download_file


def main():
    """Handles calling this module as a script

    :return: None
    """
    log = logging.getLogger(mod_logger + '.main')
    parser = argparse.ArgumentParser(description='Search for and retrieve artifacts from Nexus')
    parser.add_argument('command', help='Command for the nexus CLI')
    parser.add_argument('-a', '--artifactId', help='Artifact ID', required=False)
    parser.add_argument('-c', '--classifier', help='Artifact Classifier', required=False)
    parser.add_argument('-d', '--destination', help='Download directory', required=False)
    parser.add_argument('-x', '--direction', help='Search direction', required=False)
    parser.add_argument('-f', '--netrc', help='Use the .netrc file for credentials', required=False,
                        action='store_true')
    parser.add_argument('-g', '--groupId', help='Group ID', required=False)
    parser.add_argument('-l', '--latest', help='Set to return only the latest', required=False,
                        action='store_true')
    parser.add_argument('-n', '--username', help='Directory to download to', required=False)
    parser.add_argument('-o', '--overwrite', help='Overwrite if the file exists', required=False,
                        action='store_true')
    parser.add_argument('-p', '--packaging', help='Artifact Packaging', required=False)
    parser.add_argument('-r', '--repo', help='Nexus repository name', required=False)
    parser.add_argument('-s', '--suppress', help='Suppress download status', required=False,
                        action='store_true')
    parser.add_argument('-t', '--sort', help='Sort type (version, group, name, repository',
                        required=False)
    parser.add_argument('-u', '--url', help='Nexus Server URL', required=False)
    parser.add_argument('-v', '--version', help='Artifact Version', required=False)
    parser.add_argument('-w', '--password', help='Directory to download to', required=False)
    args = parser.parse_args()

    # Valid commands
    valid_commands = ['get', 'search']
    valid_commands_str = 'Valid commands: {c}'.format(c=', '.join(map(str, valid_commands)))

    # Get the command
    command = args.command.strip()
    if command not in valid_commands:
        print('Invalid command found [{c}]\n'.format(c=command) + valid_commands_str)

    # Determine whether to suppress status
    suppress_status = False
    if args.suppress:
        suppress_status = True

    # Determine whether to overwrite the local downloaded file if it exists
    overwrite = False
    if args.overwrite:
        overwrite = True

    # Determine whether to retrieve the latest artifact
    latest = False
    if args.latest:
        latest = True

    # Determine the destination dir -- default is the downloads directory
    destination_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    if args.destination:
        destination_dir = args.destination

    # Default username/password
    username = None
    password = None

    # Check for the --netrc arg to see if we should read credentials from that file
    if args.netrc:
        log.info('Using the ~/.netrc file for authentication...')
        base_url = args.url.lstrip('https://')
        try:
            secrets = netrc().authenticators(base_url)
        except NetrcParseError as exc:
            log.error('Problem reading the ~/.netrc file\n{e}\n{t}'.format(e=str(exc), t=traceback.format_exc()))
            return 1
        if len(secrets) >= 3:
            username = secrets[0]
            password = secrets[2]
        else:
            log.error('Read the ~/.netrc file but the list returned was missing data')
            return 2
    elif all([args.username, args.password]):
        log.info('Using the provided username/password for authentication...')
        username = args.username
        password = args.password
    else:
        log.info('Not providing credentials for authentication...')

    if args.command == 'get':
        # Attempt to download the artifact
        try:
            get_artifact_nexus(
                base_url=args.url,
                repository=args.repo,
                group_id=args.groupId,
                artifact_id=args.artifactId,
                packaging=args.packaging,
                destination_dir=destination_dir,
                version=args.version,
                classifier=args.classifier,
                suppress_status=suppress_status,
                overwrite=overwrite,
                username=username,
                password=password
            )
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            log.error('[{n}] caught unable for download artifact from Nexus:\n{e}\n{t}'.format(
                n=type(exc).__name__, e=str(exc), t=traceback.format_exc()))
            return 3
    elif args.command == 'search':
        # Search for the artifacts
        try:
            search_cli(
                base_url=args.url,
                repository=args.repo,
                group=args.groupId,
                name=args.artifactId,
                extension=args.packaging,
                sort_type=args.sort,
                direction=args.direction,
                version=args.version,
                classifier=args.classifier,
                latest=latest,
                username=username,
                password=password
            )
        except RuntimeError as exc:
            log.error('[{n}] caught searching Nexus:\n{e}\n{t}'.format(
                n=type(exc).__name__, e=str(exc), t=traceback.format_exc()))
            return 4
    else:
        print('Command is not supported: {c}'.format(c=args.command))

    log.debug('Completed running the nexus CLI')
    return 0


if __name__ == '__main__':
    res = main()
    sys.exit(res)
