#!/usr/bin/python

"""Module: nexus

This module provides simple method of fetching artifacts from a nexus
repository.

"""
import logging
import os
import time
import argparse
import xml.etree.ElementTree as elementTree

import requests
from requests.auth import HTTPBasicAuth

from .bash import mkdir_p
from .exceptions import CommandError

__author__ = 'Joe Yennaco'

# Set up logger name for this module
try:
    from .logify import Logify
except ImportError:
    Logify = None
    mod_logger = 'nexus'
else:
    mod_logger = Logify.get_name() + '.nexus'

# Sample Nexus URL
sample_nexus_url = 'https://nexus.jackpinetech.com/nexus/service/local/artifact/maven/redirect'

sample_nexus_base_url = 'https://nexus.jackpinetech.com'


def query_nexus(query_url, timeout_sec, basic_auth=None):
    """Queries Nexus for an artifact

    :param query_url: (str) Query URL
    :param timeout_sec: (int) query timeout
    :param basic_auth (HTTPBasicAuth) object or none
    :return: requests.Response object
    :raises: RuntimeError
    """
    log = logging.getLogger(mod_logger + '.query_nexus')

    # Attempt to query Nexus
    retry_sec = 5
    max_retries = 6
    try_num = 1
    query_success = False
    nexus_response = None
    while try_num <= max_retries:
        if query_success:
            break
        log.debug('Attempt # {n} of {m} to query the Nexus URL: {u}'.format(n=try_num, u=query_url, m=max_retries))
        try:
            nexus_response = requests.get(query_url, auth=basic_auth, stream=True, timeout=timeout_sec)
        except requests.exceptions.Timeout as exc:
            msg = 'Nexus initial query timed out after {t} seconds:\n{e}'.format(
                t=timeout_sec, r=retry_sec, e=str(exc))
            log.warning(msg)
            if try_num < max_retries:
                log.info('Retrying query in {t} sec...'.format(t=retry_sec))
                time.sleep(retry_sec)
        except (requests.exceptions.RequestException, requests.exceptions.ConnectionError) as exc:
            msg = 'Nexus initial query failed with the following exception:\n{e}'.format(r=retry_sec, e=str(exc))
            log.warning(msg)
            if try_num < max_retries:
                log.info('Retrying query in {t} sec...'.format(t=retry_sec))
                time.sleep(retry_sec)
        else:
            query_success = True
        try_num += 1

    if not query_success:
        msg = 'Unable to query Nexus after {m} attempts using URL: {u}'.format(
            u=query_url, m=max_retries)
        log.error(msg)
        raise RuntimeError(msg)

    if nexus_response.status_code != 200:
        msg = 'Nexus request returned code {c}, unable to query Nexus using URL: {u}'.format(
            u=query_url, c=nexus_response.status_code)
        log.error(msg)
        raise RuntimeError(msg)
    return nexus_response


def get_artifact(suppress_status=False, nexus_url=sample_nexus_url, timeout_sec=600, overwrite=True,
                 username=None, password=None, **kwargs):
    """Retrieves an artifact from Nexus

    :param suppress_status: (bool) Set to True to suppress printing download status
    :param nexus_url: (str) URL of the Nexus Server
    :param timeout_sec: (int) Number of seconds to wait before
        timing out the artifact retrieval.
    :param overwrite: (bool) True overwrites the file on the local system if it exists,
        False does will log an INFO message and exist if the file already exists
    :param username: (str) username for basic auth
    :param password: (str) password for basic auth
    :param kwargs:
        group_id: (str) The artifact's Group ID in Nexus
        artifact_id: (str) The artifact's Artifact ID in Nexus
        packaging: (str) The artifact's packaging (e.g. war, zip)
        version: (str) Version of the artifact to retrieve (e.g.
            LATEST, 4.8.4, 4.9.0-SNAPSHOT)
        destination_dir: (str) Full path to the destination directory
        classifier: (str) The artifact's classifier (e.g. bin)
    :return: None
    :raises: TypeError, ValueError, OSError, RuntimeError
    """
    log = logging.getLogger(mod_logger + '.get_artifact')

    required_args = ['group_id', 'artifact_id', 'packaging', 'version', 'destination_dir']

    if not isinstance(overwrite, bool):
        msg = 'overwrite arg must be a string, found: {t}'.format(t=overwrite.__class__.__name__)
        log.error(msg)
        raise TypeError(msg)

    if not isinstance(nexus_url, str):
        msg = 'nexus_url arg must be a string, found: {t}'.format(t=nexus_url.__class__.__name__)
        log.error(msg)
        raise TypeError(msg)

    log.debug('Using Nexus Server URL: {u}'.format(u=nexus_url))

    # Ensure the required args are supplied, and that they are all strings
    for required_arg in required_args:
        try:
            assert required_arg in kwargs
        except AssertionError as exc:
            msg = 'A required arg was not supplied. Required args are: group_id, artifact_id, classifier, version, ' \
                  'packaging and destination_dir\n{e}'
            log.error(msg)
            raise ValueError(msg) from exc
        if not isinstance(kwargs[required_arg], str):
            msg = 'Arg {a} should be a string'.format(a=required_arg)
            log.error(msg)
            raise TypeError(msg)

    # Set variables to be used in the REST call
    group_id = kwargs['group_id']
    artifact_id = kwargs['artifact_id']
    version = kwargs['version']
    packaging = kwargs['packaging']
    destination_dir = kwargs['destination_dir']

    # Ensure the destination directory exists
    if not os.path.isdir(destination_dir):
        log.debug('Specified destination_dir not found on file system, creating: {d}'.format(d=destination_dir))
        try:
            mkdir_p(destination_dir)
        except CommandError:
            msg = 'Unable to create destination directory: {d}'.format(d=destination_dir)
            raise OSError(msg)

    # Set the classifier if it was provided
    classifier = None
    if 'classifier' in kwargs:
        if isinstance(kwargs['classifier'], str):
            classifier = kwargs['classifier']
            log.debug('Using classifier: {c}'.format(c=classifier))
        else:
            log.warning('Arg classifier provided but it was not an instance of str')

    # Set the repo if it was provided
    repo = None
    if 'repo' in kwargs:
        if isinstance(kwargs['repo'], str):
            repo = kwargs['repo']
            log.debug('Using repo: {r}'.format(r=repo))

    # Determine the repo based on the version
    if repo is None:
        repo_test = version.lower().strip()
        log.debug('Checking if the version {v} is a release or snapshot...'.format(v=repo_test))
        # Determine the repo based on the version
        if ('snapshot' in repo_test) or (repo_test == 'latest'):
            repo = 'snapshots'
        else:
            repo = 'releases'
        log.info('Based on the version {v}, determined repo: {r}'.format(v=version, r=repo))

    # Construct the parameter string
    params = 'g=' + group_id + '&a=' + artifact_id + '&v=' + version + '&r=' + repo + '&p=' + packaging

    # Add the classifier if it was provided
    if classifier is not None:
        params = params + '&c=' + classifier

    # Determine the auth based on username and password
    basic_auth = None
    if (username is not None) and (password is not None):
        log.info('Using the provided username/password for basic authentication...')
        basic_auth = HTTPBasicAuth(username, password)

    # Build the query URL
    query_url = nexus_url + '?' + params

    # Set up for download attempts
    retry_sec = 5
    max_retries = 6
    try_num = 1
    download_success = False
    dl_err = None
    failed_attempt = False

    # Start the retry loop
    while try_num <= max_retries:

        # Break the loop if the download was successful
        if download_success:
            break

        log.info('Attempting to query Nexus for the Artifact using URL:  {u}'.format(u=query_url))
        try:
            nexus_response = query_nexus(query_url=query_url, timeout_sec=timeout_sec, basic_auth=basic_auth)
        except RuntimeError as exc:
            msg = 'There was a problem querying Nexus URL: {u}'.format(
                u=query_url)
            log.error(msg)
            raise RuntimeError(msg) from exc

        # Attempt to get the content-length
        file_size = 0
        try:
            file_size = int(nexus_response.headers['Content-Length'])
        except(KeyError, ValueError):
            log.debug('Could not get Content-Length, suppressing download status...')
            suppress_status = True
        else:
            log.info('Artifact file size: {s}'.format(s=file_size))

        # Determine the full download file path
        file_name = nexus_response.url.split('/')[-1]
        download_file = os.path.join(destination_dir, file_name)

        # Attempt to download the content from the response
        log.info('Attempting to download content of size {s} from Nexus to file: {d}'.format(
            s=file_size, d=download_file))

        # Remove the existing file if it exists, or exit if the file exists, overwrite is set,
        # and there was not a previous failed attempted download
        if os.path.isfile(download_file) and overwrite:
            log.debug('File already exists, removing: {d}'.format(d=download_file))
            os.remove(download_file)
        elif os.path.isfile(download_file) and not overwrite and not failed_attempt:
            log.info('File already downloaded, and overwrite is set to False.  The Artifact will '
                     'not be retrieved from Nexus: {f}.  To overwrite the existing downloaded file, '
                     'set overwrite=True'.format(f=download_file))
            return

        # Attempt to download content
        log.debug('Attempt # {n} of {m} to download content from the Nexus response'.format(n=try_num, m=max_retries))
        chunk_size = 1024
        file_size_dl = 0
        try:
            with open(download_file, 'wb') as f:
                for chunk in nexus_response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        file_size_dl += len(chunk)
                        status = r"%10d  [%3.2f%%]" % (file_size_dl, file_size_dl * 100. / file_size)
                        status += chr(8)*(len(status)+1)
                        if not suppress_status:
                            print(status),
        except(requests.exceptions.ConnectionError, requests.exceptions.RequestException, OSError) as exc:
            dl_err = 'There was an error reading content from the Nexus response. Downloaded ' \
                     'size: {s}.\n{e}'.format(s=file_size_dl, t=retry_sec, e=str(exc))
            failed_attempt = True
            log.warning(dl_err)
            if try_num < max_retries:
                log.info('Retrying download in {t} sec...'.format(t=retry_sec))
                time.sleep(retry_sec)
        else:
            log.info('File download of size {s} completed without error: {f}'.format(s=file_size_dl, f=download_file))
            failed_attempt = False
            download_success = True
        try_num += 1

    # Raise an exception if the download did not complete successfully
    if not download_success:
        msg = 'Unable to download file content from Nexus after {n} attempts'.format(n=max_retries)
        if dl_err:
            msg += '\n{m}'.format(m=dl_err)
        log.error(msg)
        raise RuntimeError(msg)


def get_artifact_nexus3(suppress_status=False, nexus_base_url=sample_nexus_base_url, repository=None,
                        timeout_sec=600, overwrite=True, username=None, password=None, **kwargs):
    """Retrieves an artifact from the Nexus 3 ReST API

    :param suppress_status: (bool) Set to True to suppress printing download status
    :param nexus_base_url: (str) Base URL of the Nexus Server (domain name portion only, see sample)
    :param repository: (str) Repository to query (e.g. snapshots) if not provided, will attempt to determine
    :param timeout_sec: (int) Number of seconds to wait before
        timing out the artifact retrieval.
    :param overwrite: (bool) True overwrites the file on the local system if it exists,
        False does will log an INFO message and exist if the file already exists
    :param username: (str) username for basic auth
    :param password: (str) password for basic auth
    :param kwargs:
        group_id: (str) The artifact's Group ID in Nexus
        artifact_id: (str) The artifact's Artifact ID in Nexus
        packaging: (str) The artifact's packaging (e.g. war, zip)
        version: (str) Version of the artifact to retrieve (e.g.
            LATEST, 4.8.4, 4.9.0-SNAPSHOT)
        destination_dir: (str) Full path to the destination directory
        classifier: (str) The artifact's classifier (e.g. bin)
    :return: None
    :raises: TypeError, ValueError, OSError, RuntimeError
    """
    log = logging.getLogger(mod_logger + '.get_artifact_nexus3')

    required_args = ['group_id', 'artifact_id', 'packaging', 'version', 'destination_dir']

    if not isinstance(overwrite, bool):
        msg = 'overwrite arg must be a string, found: {t}'.format(t=overwrite.__class__.__name__)
        log.error(msg)
        raise TypeError(msg)

    if not isinstance(nexus_base_url, str):
        msg = 'nexus_url arg must be a string, found: {t}'.format(t=nexus_base_url.__class__.__name__)
        log.error(msg)
        raise TypeError(msg)

    log.debug('Using Nexus Server URL: {u}'.format(u=nexus_base_url))

    # Ensure the required args are supplied, and that they are all strings
    for required_arg in required_args:
        try:
            assert required_arg in kwargs
        except AssertionError as exc:
            msg = 'A required arg was not supplied. Required args are: group_id, artifact_id, classifier, version, ' \
                  'packaging and destination_dir'
            log.error(msg)
            raise ValueError(msg) from exc
        if not isinstance(kwargs[required_arg], str):
            msg = 'Arg {a} should be a string'.format(a=required_arg)
            log.error(msg)
            raise TypeError(msg)

    # Set variables to be used in the REST call
    group_id = kwargs['group_id']
    artifact_id = kwargs['artifact_id']
    version = kwargs['version']
    packaging = kwargs['packaging']
    destination_dir = kwargs['destination_dir']

    # Ensure the destination directory exists
    if not os.path.isdir(destination_dir):
        log.debug('Specified destination_dir not found on file system, creating: {d}'.format(d=destination_dir))
        try:
            mkdir_p(destination_dir)
        except CommandError:
            msg = 'Unable to create destination directory: {d}'.format(d=destination_dir)
            raise OSError(msg)

    # Determine the auth based on username and password
    basic_auth = None
    if (username is not None) and (password is not None):
        log.info('Using the provided username/password for basic authentication...')
        basic_auth = HTTPBasicAuth(username, password)

    # Set the classifier if it was provided
    classifier = None
    if 'classifier' in kwargs:
        if isinstance(kwargs['classifier'], str):
            classifier = kwargs['classifier']
            log.debug('Using classifier: {c}'.format(c=classifier))
        else:
            log.warning('Arg classifier provided but it was not an instance of str')

    # Determine the repository (snapshots or releases)
    if not repository:
        if 'SNAPSHOT' in version:
            repository = 'snapshots'
        else:
            repository = 'releases'
    log.debug('Using repository: {r}'.format(r=repository))

    # Compute the query URL
    group_id_url = group_id.replace('.', '/')

    # Get the Maven metadata
    query_url_version = nexus_base_url + '/repository/{r}/{g}/{a}/{v}'.format(
        r=repository, g=group_id_url, a=artifact_id, v=version
    )

    if 'snapshot' in repository.lower():
        # Query nexus for metadata to determine the proper file name
        query_url_metadata = query_url_version + '/maven-metadata.xml'

        log.info('Attempting to query Nexus for the snapshot metadata using URL:  {u}'.format(u=query_url_metadata))
        try:
            nexus_response = query_nexus(query_url=query_url_metadata, timeout_sec=timeout_sec, basic_auth=basic_auth)
        except RuntimeError as exc:
            msg = 'There was a problem querying Nexus URL: {u}'.format(u=query_url_metadata)
            log.error(msg)
            raise RuntimeError(msg) from exc

        if nexus_response.status_code != 200:
            raise RuntimeError('Bad response from Nexus metadata URL [{c}]: {u}'.format(
                c=nexus_response.status_code, u=query_url_metadata))

        # Parse the XML output
        root = elementTree.fromstring(nexus_response.text)
        log.info('Attempting to find the value of the file name...')
        try:
            value = root.find('versioning').find('snapshotVersions').find('snapshotVersion').find('value')
        except AttributeError as exc:
            msg = 'AttributeError: Unable to find versioning/snapshotVersions/snapshotVersion/value'
            raise ValueError(msg) from exc

        # Ensure a value was found
        if value is None:
            raise ValueError('Unable to determine the value of the snapshot version')

        # Get the text version
        text_version = value.text
        log.info('Found version value: {t}'.format(t=text_version))

        # Determine the artifact file name
        artifact_file_name = '{a}-{t}'.format(
            a=artifact_id,
            t=text_version
        )
    else:
        # Construct the file name for releases (e.g. cons3rt-backend-install-18.14.0-package-otto.zip)
        artifact_file_name = '{a}-{v}'.format(
            a=artifact_id,
            v=version
        )

    # Add classifier if provided and packaging
    if classifier:
        artifact_file_name += '-{c}'.format(c=classifier)
    artifact_file_name += '.{p}'.format(p=packaging)
    log.info('Using artifact file name: {n}'.format(n=artifact_file_name))

    # Determine the full query URL
    query_url = query_url_version + '/{n}'.format(n=artifact_file_name)
    log.info('Using Nexus query URL: {u}'.format(u=query_url))

    # Set up for download attempts
    retry_sec = 5
    max_retries = 6
    try_num = 1
    download_success = False
    dl_err = None
    failed_attempt = False

    # Start the retry loop
    while try_num <= max_retries:

        # Break the loop if the download was successful
        if download_success:
            break

        log.info('Attempting to query Nexus for the Artifact using URL:  {u}'.format(u=query_url))
        try:
            nexus_response = query_nexus(query_url=query_url, timeout_sec=timeout_sec, basic_auth=basic_auth)
        except RuntimeError as exc:
            msg = 'There was a problem querying Nexus URL: {u}'.format(u=query_url)
            log.error(msg)
            raise RuntimeError(msg) from exc

        # Attempt to get the content-length
        file_size = 0
        try:
            file_size = int(nexus_response.headers['Content-Length'])
        except(KeyError, ValueError):
            log.debug('Could not get Content-Length, suppressing download status...')
            suppress_status = True
        else:
            log.info('Artifact file size: {s}'.format(s=file_size))

        # Determine the full download file path
        file_name = nexus_response.url.split('/')[-1]
        download_file = os.path.join(destination_dir, file_name)

        # Attempt to download the content from the response
        log.info('Attempting to download content of size {s} from Nexus to file: {d}'.format(
            s=file_size, d=download_file))

        # Remove the existing file if it exists, or exit if the file exists, overwrite is set,
        # and there was not a previous failed attempted download
        if os.path.isfile(download_file) and overwrite:
            log.debug('File already exists, removing: {d}'.format(d=download_file))
            os.remove(download_file)
        elif os.path.isfile(download_file) and not overwrite and not failed_attempt:
            log.info('File already downloaded, and overwrite is set to False.  The Artifact will '
                     'not be retrieved from Nexus: {f}.  To overwrite the existing downloaded file, '
                     'set overwrite=True'.format(f=download_file))
            return

        # Attempt to download content
        log.debug('Attempt # {n} of {m} to download content from the Nexus response'.format(n=try_num, m=max_retries))
        chunk_size = 1024
        file_size_dl = 0
        try:
            with open(download_file, 'wb') as f:
                for chunk in nexus_response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        file_size_dl += len(chunk)
                        status = r"%10d  [%3.2f%%]" % (file_size_dl, file_size_dl * 100. / file_size)
                        status += chr(8)*(len(status)+1)
                        if not suppress_status:
                            print(status),
        except(requests.exceptions.ConnectionError, requests.exceptions.RequestException, OSError) as exc:
            dl_err = 'There was an error reading content from the Nexus response. Downloaded ' \
                     'size: {s}.\n{e}'.format(s=file_size_dl, t=retry_sec, e=str(exc))
            failed_attempt = True
            log.warning(dl_err)
            if try_num < max_retries:
                log.info('Retrying download in {t} sec...'.format(t=retry_sec))
                time.sleep(retry_sec)
        else:
            log.info('File download of size {s} completed without error: {f}'.format(s=file_size_dl, f=download_file))
            failed_attempt = False
            download_success = True
        try_num += 1

    # Raise an exception if the download did not complete successfully
    if not download_success:
        msg = 'Unable to download file content from Nexus after {n} attempts'.format(n=max_retries)
        if dl_err:
            msg += '\n{m}'.format(m=dl_err)
        log.error(msg)
        raise RuntimeError(msg)


def main():
    """Handles calling this module as a script

    :return: None
    """
    log = logging.getLogger(mod_logger + '.main')
    parser = argparse.ArgumentParser(description='This Python module retrieves artifacts from Nexus.')
    parser.add_argument('-u', '--url', help='Nexus Server URL', required=False)
    parser.add_argument('-g', '--groupId', help='Group ID', required=True)
    parser.add_argument('-a', '--artifactId', help='Artifact ID', required=True)
    parser.add_argument('-v', '--version', help='Artifact Version', required=True)
    parser.add_argument('-c', '--classifier', help='Artifact Classifier', required=False)
    parser.add_argument('-p', '--packaging', help='Artifact Packaging', required=True)
    parser.add_argument('-r', '--repo', help='Nexus repository name', required=False)
    parser.add_argument('-d', '--destinationDir', help='Directory to download to', required=True)
    parser.add_argument('-n', '--username', help='Directory to download to', required=True)
    parser.add_argument('-w', '--password', help='Directory to download to', required=True)
    args = parser.parse_args()
    try:
        get_artifact(
            nexus_url=args.url,
            group_id=args.groupId,
            artifact_id=args.artifactId,
            version=args.version,
            classifier=args.classifier,
            packaging=args.packaging,
            repo=args.repo,
            destination_dir=args.destinationDir,
            username=args.username,
            password=args.password
        )
    except Exception as e:
        msg = 'Caught exception {n}, unable for download artifact from Nexus\n{s}'.format(
            n=e.__class__.__name__, s=e)
        log.error(msg)
        return


if __name__ == '__main__':
    main()
