#!/usr/bin/env python

import logging
import os
import sys
import time
import traceback

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, SSLError
from requests_toolbelt import MultipartEncoder
from urllib3.util import Retry
from urllib3.exceptions import MaxRetryError

from .logify import Logify
from .exceptions import Cons3rtClientError

# Set up logger name for this module
mod_logger = Logify.get_name() + '.httpclient'

# Default timeout values
default_connect_timeout = 27.05
default_read_timeout = 99
default_read_timeout_asset_downloads = 900


class Client:

    def __init__(self, base, max_retry_attempts=10, retry_time_sec=5):
        self.base = base
        self.max_retry_attempts = max_retry_attempts
        self.retry_time_sec = retry_time_sec
        if self.base:
            if not self.base.endswith('/'):
                self.base = self.base + '/'
        self.cls_logger = mod_logger + '.Client'

    @staticmethod
    def get_auth_headers(rest_user):
        """Returns the auth portion of the headers including:
        * token
        * username (only for non-cert auth sites)

        :param rest_user: (RestUser) user info
        :return: (dict) headers
        """
        if rest_user is None:
            raise Cons3rtClientError('rest_user provided was None')

        if rest_user.cert_file_path:
            return {
                'token': rest_user.token,
                'Accept': 'application/json'
            }
        else:
            return {
                'username': rest_user.username,
                'token': rest_user.token,
                'Accept': 'application/json'
            }

    @staticmethod
    def validate_target(target):
        """ Validates that a target was provided and is a string
        :param target: the target url for the http request
        :return: void
        :raises: Cons3rtClientError
        """

        if target is None or not isinstance(target, str):
            raise Cons3rtClientError('Invalid target arg provided')

    @staticmethod
    def __http_exception__(exc, msg_part=None, start_time=None):
        """Raises an exception with an elapsed time from a provided start time

        :param exc: the exception
        :param start_time: time.time() seconds in epoch time
        :param msg_part: Optional part of an error message
        :return: None
        :raises: Exception
        """
        err_msg = ''.format(n=exc[1].__class__.__name__)
        if msg_part:
            err_msg += msg_part
        if start_time:
            err_msg += ' after {t} seconds'.format(t=str(round(time.time() - start_time, 4)))
        err_msg += '\n{e}'.format(e=str(exc[1]))
        raise Cons3rtClientError(err_msg)

    def http_get(self, rest_user, target):
        """Runs an HTTP GET request to the CONS3RT ReST API

        :param rest_user: (RestUser) user info
        :param target: (str) URL
        :return: http response
        """
        log = logging.getLogger(self.cls_logger + '.http_get')

        self.validate_target(target)

        # Set the URL
        url = self.base + target
        log.debug('Querying http GET with URL: {u}'.format(u=url))

        # Determine the headers
        headers = self.get_auth_headers(rest_user=rest_user)

        try:
            response = http_get_with_retries(url=url, headers=headers, client_cert_path=rest_user.cert_file_path,
                                             cert_bundle_path=rest_user.cert_bundle)
        except Cons3rtClientError:
            raise
        return response

    def http_get_download(self, rest_user, target, connect_timeout=default_connect_timeout,
                          read_timeout=default_read_timeout_asset_downloads):
        """Runs an HTTP GET request to the CONS3RT ReST API

        :param rest_user: (RestUser) user info
        :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
        :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
        :param target: (str) URL
        :return: http response
        """
        log = logging.getLogger(self.cls_logger + '.http_get_download')
        self.validate_target(target)

        # Set the URL
        url = self.base + target
        log.debug('Querying http GET with URL: {u}'.format(u=url))

        # Determine the headers
        headers = self.get_auth_headers(rest_user=rest_user)
        headers['Accept'] = 'application/octet-stream'

        try:
            response = http_get_with_retries(url=url, headers=headers, client_cert_path=rest_user.cert_file_path,
                                             cert_bundle_path=rest_user.cert_bundle, connect_timeout=connect_timeout,
                                             read_timeout=read_timeout)
        except Cons3rtClientError:
            raise
        return response

    def http_delete(self, rest_user, target, content=None, keep_alive=False, connect_timeout=default_connect_timeout,
                    read_timeout=default_read_timeout):
        """Runs an HTTP DELETE request to the CONS3RT ReST API

        :param rest_user: (RestUser) user info
        :param target: (str) URL
        :param content: (dict) content for the request
        :param keep_alive: (bool) set True to send a keep alive with the request
        :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
        :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
        :return: http response
        """
        log = logging.getLogger(self.cls_logger + '.http_delete')
        self.validate_target(target)
        url = self.base + target
        log.debug('Querying http DELETE with URL: {u}'.format(u=url))

        headers = self.get_auth_headers(rest_user=rest_user)
        headers['Content-Type'] = 'application/json'

        if keep_alive:
            headers['Connection'] = 'Keep-Alive'

        attempt_num = 1
        err_msg_tally = ''
        while True:
            if attempt_num >= self.max_retry_attempts:
                msg = 'Max attempts exceeded: {n}\n{e}'.format(n=str(self.max_retry_attempts), e=err_msg_tally)
                raise Cons3rtClientError(msg)
            err_msg = ''
            try:
                if content is None:
                    response = requests.delete(
                        url,
                        headers=headers,
                        cert=rest_user.cert_file_path,
                        verify=rest_user.cert_bundle,
                        timeout=(connect_timeout, read_timeout)
                    )
                else:
                    response = requests.delete(
                        url, headers=headers, data=content, cert=rest_user.cert_file_path, verify=rest_user.cert_bundle)
            except RequestException as exc:
                err_msg += 'RequestException on DELETE to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except SSLError as exc:
                err_msg += 'SSLError on DELETE to URL: {u}\n{e}'.format(u=url, e=str(exc))
            else:
                return response
            err_msg_tally += err_msg + '\n'
            log.warning('Problem encountered, retrying in {n} sec: {e}'.format(n=str(self.retry_time_sec), e=err_msg))
            attempt_num += 1
            time.sleep(self.retry_time_sec)

    def http_post(self, rest_user, target, content_data=None, content_file=None, content_type='application/json',
                  connect_timeout=default_connect_timeout, read_timeout=default_read_timeout):
        """Makes an HTTP Post to the requested URL

        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_file: (str) path to the content file
        :param content_data: (str or dict) body data
        :param content_type: (str) Content-Type, default is application/json
        :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
        :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
        :return: (str) HTTP Response or None
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.http_post')
        self.validate_target(target)
        url = self.base + target
        log.debug('Querying http POST with URL: {u}'.format(u=url))

        headers = self.get_auth_headers(rest_user=rest_user)
        headers['Content-Type'] = '{t}'.format(t=content_type)
        content_result, content = get_content(content_file=content_file, content_data=content_data)
        if not content_result:
            raise Cons3rtClientError('Problem determining the content to send')

        # Add content type if content was provided
        if content:
            headers['Content-Type'] = '{t}'.format(t=content_type)
            log.debug('Making POST with content:\n{c}'.format(c=str(content)))
        else:
            log.debug('Making POST with no content')

        # Make the POST request
        attempt_num = 1
        err_msg_tally = ''
        while True:
            if attempt_num >= self.max_retry_attempts:
                msg = 'Max attempts exceeded: {n}\n{e}'.format(n=str(self.max_retry_attempts), e=err_msg_tally)
                raise Cons3rtClientError(msg)
            err_msg = ''
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    data=content,
                    cert=rest_user.cert_file_path,
                    verify=rest_user.cert_bundle,
                    timeout=(connect_timeout, read_timeout)
                )
            except SSLError as exc:
                err_msg += 'SSLError on POST to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except requests.ConnectionError as exc:
                err_msg += 'ConnectionError on POST to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except requests.Timeout as exc:
                err_msg += 'Timeout on POST to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except RequestException as exc:
                err_msg += 'RequestException on POST to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except MaxRetryError as exc:
                err_msg += 'MaxRetryError on GET to URL [{u}] with reason [{r}]\n{e}'.format(
                    u=exc.url, r=exc.reason, e=str(exc))
            except Exception as exc:
                err_msg += 'Generic exception on POST to URL: {u}\n{e}'.format(u=url, e=str(exc))
            else:
                return response
            err_msg_tally += err_msg + '\n'
            log.warning('Problem encountered, retrying in {n} sec: {e}'.format(n=str(self.retry_time_sec), e=err_msg))
            attempt_num += 1
            time.sleep(self.retry_time_sec)

    def http_put(self, rest_user, target, content_data=None, content_file=None, content_type='application/json',
                 connect_timeout=default_connect_timeout, read_timeout=default_read_timeout):
        """Makes an HTTP Post to the requested URL

        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_data: (str or dict) body data
        :param content_file: (str) path to the content file containing body data
        :param content_type: (str) Content-Type, default is application/json
        :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
        :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
        :return: (str) HTTP Response or None
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.http_put')
        self.validate_target(target)
        url = self.base + target
        log.debug('Querying http PUT with URL: {u}'.format(u=url))
        headers = self.get_auth_headers(rest_user=rest_user)
        content_result, content = get_content(content_file=content_file, content_data=content_data)
        if not content_result:
            raise Cons3rtClientError('Problem determining the content to send')

        # Add content type if content was provided
        if content:
            headers['Content-Type'] = '{t}'.format(t=content_type)

        # Make the PUT request
        attempt_num = 1
        err_msg_tally = ''
        while True:
            if attempt_num >= self.max_retry_attempts:
                msg = 'Max attempts exceeded: {n}\n{e}'.format(n=str(self.max_retry_attempts), e=err_msg_tally)
                raise Cons3rtClientError(msg)
            err_msg = ''
            try:
                response = requests.put(
                    url,
                    headers=headers,
                    data=content,
                    cert=rest_user.cert_file_path,
                    verify=rest_user.cert_bundle,
                    timeout=(connect_timeout, read_timeout)
                )
            except SSLError as exc:
                err_msg += 'SSLError on PUT to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except requests.ConnectionError as exc:
                err_msg += 'ConnectionError on PUT to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except requests.Timeout as exc:
                err_msg += 'Timeout on PUT to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except RequestException as exc:
                err_msg += 'RequestException on PUT to URL: {u}\n{e}'.format(u=url, e=str(exc))
            except MaxRetryError as exc:
                err_msg += 'MaxRetryError on GET to URL [{u}] with reason [{r}]\n{e}'.format(
                    u=exc.url, r=exc.reason, e=str(exc))
            except Exception as exc:
                err_msg += 'Generic exception on PUT to URL: {u}\n{e}'.format(u=url, e=str(exc))
            else:
                return response
            err_msg_tally += err_msg + '\n'
            log.warning('Problem encountered, retrying in {n} sec: {e}'.format(n=str(self.retry_time_sec), e=err_msg))
            attempt_num += 1
            time.sleep(self.retry_time_sec)

    def http_multipart(self, method, rest_user, target, content_file, connect_timeout=default_connect_timeout,
                       read_timeout=default_read_timeout):
        """Makes an HTTP Multipart request to upload a file

        :param method: (str) PUT or POST
        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_file: (str) path to the content file
        :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
        :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
        :return: (str) HTTP Response or None
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.http_multipart')

        # Determine the method
        if method.upper() == 'PUT':
            method = 'PUT'
        elif method.upper() == 'POST':
            method = 'POST'
        else:
            raise Cons3rtClientError('http_multipart supports PUT or POST, found: {m}'.format(m=method))

        # Ensure a content file was provided
        if not content_file:
            raise Cons3rtClientError('content_file arg is None')

        # Determine the full URL
        self.validate_target(target)
        url = self.base + target
        log.debug('Querying http {m} to URL: {u}'.format(m=method, u=url))

        # Set headers
        headers = self.get_auth_headers(rest_user=rest_user)
        headers['Accept'] = 'application/json'
        headers['Connection'] = 'Keep-Alive'
        headers['Expect'] = '100-continue'
        # file_name = content_file.split(os.sep)[-1]

        # Open the content_file to create the multipart encoder
        start_time = time.time()
        with open(content_file, 'rb') as f:

            # Create the MultipartEncoder (thanks requests_toolbelt!)
            form = MultipartEncoder({
                "file": ("asset.zip", f, "application/octet-stream"),
                "filename": "asset.zip"
            })

            # Add the Content-Type
            headers['Content-Type'] = form.content_type
            # headers['Content-Transfer-Encoding'] = 'binary'
            # headers['Content-Disposition'] = 'form-data; name=file filename={f}'.format(f=file_name)

            # Create the request
            s = requests.Session()

            # Add the retries
            retries = Retry(
                total=5,
                backoff_factor=0.5,
                status_forcelist=[413, 429, 500, 502, 503, 504],
                allowed_methods={'GET'},
            )
            s.mount('https://', HTTPAdapter(max_retries=retries))

            # Handle the cert auth
            if rest_user.cert_file_path:
                s.cert = rest_user.cert_file_path
                log.info('Adding client certificate to the MultiPart upload request: {c}'.format(
                    c=s.cert))

            # Handle the cert bundle
            if rest_user.cert_bundle is None:
                log.info('Cert bundle is none, setting to True to enable verification')
                s.verify = True
            else:
                s.verify = rest_user.cert_bundle
            log.info('Using SSL verify setting for the MultiPart upload: {v}'.format(v=str(s.verify)))

            # Create the request
            req = requests.Request(method, url, data=form, headers=headers)

            # TODO ensure this works by prepping with the session to allow cookies and saved data to work
            #prepped = req.prepare()
            prepped = s.prepare_request(request=req)

            # Print the request info
            log.info('Request URL: {u}'.format(u=url))
            redacted_headers = dict(prepped.headers)
            redacted_headers['token'] = 'REDACTED'
            log.info('Prepped headers: {h}'.format(h=redacted_headers))
            log.info('Making request with method: [{m}]'.format(m=method))

            # Attempt to send the request
            attempt_num = 1
            err_msg_tally = ''
            while True:
                if attempt_num >= self.max_retry_attempts:
                    err_msg += 'Max attempts exceeded: {n}\n{e}'.format(n=str(self.max_retry_attempts), e=err_msg_tally)
                    self.__http_exception__(
                        exc=sys.exc_info(),
                        msg_part=err_msg_tally,
                        start_time=start_time)
                err_msg = ''

                # Send the request
                try:
                    response = s.send(prepped, timeout=(connect_timeout, read_timeout))
                except SSLError as exc:
                    err_msg += 'SSLError on {m} to URL: {u}\n{e}'.format(u=url, m=method, e=str(exc))
                except requests.ConnectionError as exc:
                    err_msg += 'ConnectionError on {m} to URL: {u}\n{e}'.format(u=url, m=method, e=str(exc))
                except requests.Timeout as exc:
                    err_msg += 'Timeout on {m} to URL: {u}\n{e}'.format(u=url, m=method, e=str(exc))
                except RequestException as exc:
                    err_msg += 'RequestException on {m} to URL: {u}\n{e}'.format(u=url, m=method, e=str(exc))
                except MaxRetryError as exc:
                    err_msg += 'MaxRetryError on GET to URL [{u}] with reason [{r}]\n{e}'.format(
                        u=exc.url, r=exc.reason, e=str(exc))
                else:
                    complete_time = time.time()
                    log.info('Request completed in {t} seconds'.format(t=str(round(complete_time - start_time, 2))))
                    return response

                err_msg_tally += err_msg + '\n'
                log.warning('Problem encountered, retrying in {n} sec: {e}'.format(
                    n=str(self.retry_time_sec), e=err_msg))
                attempt_num += 1
                time.sleep(self.retry_time_sec)

    def http_put_multipart(self, rest_user, target, content_file):
        """Makes an HTTP PUT Multipart request to upload a file

        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_file: (str) path to the content file
        :return: (str) HTTP Response or None
        :raises: Cons3rtClientError
        """
        return self.http_multipart(
            method='PUT',
            rest_user=rest_user,
            target=target,
            content_file=content_file
        )

    def http_post_multipart(self, rest_user, target, content_file):
        """Makes an HTTP POST Multipart request to upload a file

        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_file: (str) path to the content file
        :return: (str) HTTP Response or None
        :raises: Cons3rtClientError
        """
        return self.http_multipart(
            method='POST',
            rest_user=rest_user,
            target=target,
            content_file=content_file
        )

    # This only exists for backwards compatibility
    def parse_response(self, response):
        log = logging.getLogger(self.cls_logger + '.parse_response')
        log.debug('Parsing response...')
        return parse_response(response=response)

    def http_download(self, rest_user, target, download_file, overwrite=True, suppress_status=True,
                      connect_timeout=default_connect_timeout, read_timeout=default_read_timeout_asset_downloads):
        """Runs an HTTP GET request to the CONS3RT ReST API

        :param rest_user: (RestUser) user info
        :param target: (str) URL
        :param download_file (str) destination file path
        :param overwrite (bool) set True to overwrite the existing file
        :param suppress_status: (bool) Set to True to suppress printing download status
        :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
        :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
        :return: (str) path to the downloaded file
        """
        log = logging.getLogger(self.cls_logger + '.http_download')
        log.info('Attempting to download target [{t}] to: {d}'.format(t=target, d=download_file))
        
        # Set up for download attempts
        retry_sec = self.retry_time_sec
        max_retries = self.max_retry_attempts
        try_num = 1
        download_success = False
        dl_err = None
        failed_attempt = False

        # Start the retry loop
        while try_num <= max_retries:
    
            # Break the loop if the download was successful
            if download_success:
                break

            log.info('Attempt # {n} of {m} to query target URL: {u}'.format(n=try_num, m=max_retries, u=target))
            try:
                response = self.http_get_download(rest_user=rest_user, target=target, connect_timeout=connect_timeout,
                                                  read_timeout=read_timeout)
            except Cons3rtClientError as exc:
                msg = 'There was a problem querying target with GET: {u}'.format(u=target)
                raise Cons3rtClientError(msg) from exc
    
            # Attempt to get the content-length
            if 'Content-Length' in response.headers.keys():
                file_size = int(response.headers['Content-Length'])
            else:
                log.debug('Could not get Content-Length, suppressing download status...')
                file_size = 0
            log.info('Download file size: [{s}] bytes'.format(s=file_size))

            # Attempt to download the content from the response
            log.info('Attempting to download content of size {s} to file: {d}'.format(s=file_size, d=download_file))

            # Remove the existing file if it exists, or exit if the file exists, overwrite is set,
            # and there was not a previous failed attempted download
            if os.path.isfile(download_file) and overwrite:
                log.info('File already exists, removing: {d}'.format(d=download_file))
                os.remove(download_file)
            elif os.path.isfile(download_file) and not overwrite and not failed_attempt:
                log.info('File already downloaded, and overwrite is set to False.  The file will '
                         'not be downloaded: {f}.  To overwrite the existing downloaded file, '
                         'set overwrite=True'.format(f=download_file))
                return
    
            # Attempt to download content
            log.info('Attempt # {n} of {m} to download content to: {d}'.format(
                n=try_num, m=max_retries, d=download_file))

            if not write_file_download(download_file=download_file, http_response=response, file_size=file_size,
                                       chunk_size=1024, suppress_status=suppress_status):
                failed_attempt = True
                if try_num < max_retries:
                    log.info('Retrying download in {t} sec...'.format(t=retry_sec))
                    time.sleep(retry_sec)
            else:
                failed_attempt = False
                download_success = True
            try_num += 1
    
        # Raise an exception if the download did not complete successfully
        if not download_success:
            msg = 'Unable to download file content after {n} attempts'.format(n=max_retries)
            if dl_err:
                msg += '\n{m}'.format(m=dl_err)
            raise Cons3rtClientError(msg)
        return download_file


def get_content(content_file=None, content_data=None):
    """Returns the content of a file, provided data, or None

    :param content_file: (str) path to the file containing content
    :param content_data: (str) actual content data
    :return: (tuple) Success (bool) and content data (str) or None
    """
    log = logging.getLogger(mod_logger + '.get_content')
    content = None
    # Read data from the file if provided
    if content_file:
        log.debug('Getting content from file: {f}'.format(f=content_file))
        try:
            with open(content_file, 'r') as f:
                content = f.read()
        except (OSError, IOError) as exc:
            log.warning('[{n}] reading contents of file: {f}\n{e}\n{t}'.format(
                n=type(exc).__name__, f=content_file, e=str(exc), t=traceback.format_exc()))
            return False, None
    # Otherwise use data provided as content
    elif content_data:
        log.debug('Getting content from provided content data')
        content = content_data
    return True, content


def http_download(url, download_file, headers=None, basic_auth=None, client_cert_path=None, cert_bundle_path=None,
                  max_retry_attempts=10, retry_time_sec=3, connect_timeout=default_connect_timeout,
                  read_timeout=default_read_timeout_asset_downloads, suppress_status=False):
    """Download the file and stream content to the download file location

    :param url: (str) URL to query
    :param download_file: (str) Path to the download file
    :param headers: (dict) headers
    :param basic_auth: (HTTPBasicAuth) Basic authentication object
    :param client_cert_path: (str) path to the client certificate
    :param cert_bundle_path: (str) path to the certificate root CA bundle
    :param max_retry_attempts: (int) maximum number of attempts
    :param retry_time_sec: (int) seconds between attempts
    :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
    :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
    :param suppress_status: (bool) Set true to suppress status output
    :return: (str) file download location
    :raises: Cons3rtClientError
    """
    log = logging.getLogger(mod_logger + '.http_download')
    attempt_num = 1
    err_msg_tally = ''



    while True:
        if attempt_num >= max_retry_attempts:
            msg = 'Max attempts exceeded: {n}\n{e}'.format(n=str(max_retry_attempts), e=err_msg_tally)
            raise Cons3rtClientError(msg)
        err_msg = ''
        try:
            with requests.get(url, headers=headers, cert=client_cert_path, verify=cert_bundle_path, auth=basic_auth,
                              stream=True, timeout=(connect_timeout, read_timeout)) as response:
                # Attempt to get the content-length
                if 'Content-Length' in response.headers.keys():
                    file_size = int(response.headers['Content-Length'])
                else:
                    log.debug('Could not get Content-Length, suppressing download status...')
                    file_size = 0
                write_file_download(http_response=response, download_file=download_file, file_size=file_size,
                                    chunk_size=1024, suppress_status=suppress_status)
        except SSLError as exc:
            err_msg += 'SSlError on GET to URL: {u}\n{e}'.format(u=url, e=str(exc))
        except requests.ConnectionError as exc:
            err_msg += 'ConnectionError on GET to URL: {u}\n{e}'.format(u=url, e=str(exc))
        except requests.Timeout as exc:
            err_msg += 'Timeout on GET to URL: {u}\n{e}'.format(u=url, e=str(exc))
        except RequestException as exc:
            err_msg += 'RequestException on GET to URL: {u}\n{e}'.format(u=url, e=str(exc))
        except MaxRetryError as exc:
            err_msg += 'MaxRetryError on GET to URL [{u}] with reason [{r}]\n{e}'.format(
                u=exc.url, r=exc.reason, e=str(exc))
        except Exception as exc:
            err_msg += '[{n}] encountered on GET to URL: {u}\n{e}'.format(n=type(exc).__name__, u=url, e=str(exc))
        else:
            return response
        err_msg_tally += err_msg + '\n'
        log.warning('Problem encountered, retrying in {n} sec: {e}'.format(n=str(retry_time_sec), e=err_msg))
        attempt_num += 1
        time.sleep(retry_time_sec)
        return download_file


def http_get_with_retries(url, headers=None, basic_auth=None, client_cert_path=None, cert_bundle_path=None,
                          max_retry_attempts=10, retry_time_sec=3, connect_timeout=default_connect_timeout,
                          read_timeout=default_read_timeout):
    """Run http get request with retries

    :param url: (str) URL to query
    :param headers: (dict) headers
    :param basic_auth: (HTTPBasicAuth) Basic authentication object
    :param client_cert_path: (str) path to the client certificate
    :param cert_bundle_path: (str) path to the certificate root CA bundle
    :param max_retry_attempts: (int) maximum number of attempts
    :param retry_time_sec: (int) seconds between attempts
    :param connect_timeout: (float) seconds to wait for the connection to succeed, should be > multiple of 3
    :param read_timeout: (int) seconds to wait in between bytes received, 99.9% it's the 1st byte
    :return: requests.Response object
    :raises: Cons3rtClientError
    """
    log = logging.getLogger(mod_logger + '.http_get_with_retries')
    attempt_num = 1
    err_msg_tally = ''

    # Build the request
    s = requests.Session()

    # Add the retries
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=[413, 429, 500, 502, 503, 504],
        allowed_methods={'GET'},
    )
    s.mount('https://', HTTPAdapter(max_retries=retries))

    # Handle the cert auth
    if client_cert_path:
        log.debug('Adding client certificate to the http GET request: {c}'.format(c=s.cert))
        s.cert = client_cert_path
        s.auth = None
    else:
        log.debug('Using basic auth for the http GET request')
        s.auth = basic_auth

    # Handle the cert bundle
    if not cert_bundle_path:
        log.debug('Cert bundle is none, setting http GET SSL verification to True...')
        s.verify = True
    else:
        log.debug('Specifying http GET with cert bundle: [{b}]'.format(b=cert_bundle_path))
        s.verify = cert_bundle_path
    log.debug('Using SSL verify setting for http GET: {v}'.format(v=str(s.verify)))

    # Create the request
    req = requests.Request('GET', url, headers=headers)

    # Prepare the request
    prepped = s.prepare_request(request=req)

    # Print the request info
    log.debug('Request URL for http GET: {u}'.format(u=url))
    redacted_headers = dict(prepped.headers)
    redacted_headers['token'] = 'REDACTED'
    log.debug('Prepped headers for http GET: {h}'.format(h=redacted_headers))

    while True:
        if attempt_num >= max_retry_attempts:
            msg = 'Max attempts exceeded: {n}\n{e}'.format(n=str(max_retry_attempts), e=err_msg_tally)
            raise Cons3rtClientError(msg)
        err_msg = ''
        try:
            response = s.send(prepped, timeout=(connect_timeout, read_timeout))
        except SSLError as exc:
            err_msg += 'SSlError on GET to URL [{u}]\n{e}'.format(u=url, e=str(exc))
        except requests.ConnectionError as exc:
            err_msg += 'ConnectionError on GET to URL [{u}]\n{e}'.format(u=url, e=str(exc))
        except requests.Timeout as exc:
            err_msg += 'Timeout on GET to URL [{u}]\n{e}'.format(u=url, e=str(exc))
        except RequestException as exc:
            err_msg += 'RequestException on GET to URL: {u}\n{e}'.format(u=url, e=str(exc))
        except MaxRetryError as exc:
            err_msg += 'MaxRetryError on GET to URL [{u}] with reason [{r}]\n{e}'.format(
                u=exc.url, r=exc.reason, e=str(exc))
        except Exception as exc:
            err_msg += '[{n}] encountered on GET to URL: {u}\n{e}'.format(n=type(exc).__name__, u=url, e=str(exc))
        else:
            return response
        err_msg_tally += err_msg + '\n'
        log.warning('Problem encountered, retrying in {n} sec: {e}'.format(n=str(retry_time_sec), e=err_msg))
        attempt_num += 1
        time.sleep(retry_time_sec)


def parse_response(response):
    log = logging.getLogger(mod_logger + '.parse_response')

    # Determine is there is content and if it needs to be decoded
    if response.content:
        log.debug('Parsing response with content: {s}'.format(s=response.content))
        if isinstance(response.content, bytes):
            log.debug('Decoding bytes: {b}'.format(b=response.content))
            decoded_content = response.content.decode('utf-8')
        else:
            decoded_content = response.content
    else:
        decoded_content = None

    # Raise an exception if a bad HTTP code was received
    if response.status_code not in [requests.codes.ok, 202]:
        msg = 'Received HTTP code [{n}] with headers:\n{h}'.format(n=str(response.status_code), h=response.headers)
        if decoded_content:
            msg += '\nand content:\n{c}'.format(c=decoded_content)
        raise Cons3rtClientError(msg)

    # Return the decoded content
    if response.status_code == requests.codes.ok:
        log.debug('Received an OK HTTP Response Code')
    elif response.status_code == 202:
        log.debug('Received an ACCEPTED HTTP Response Code (202)')
    log.debug('Parsed decoded content: {c}'.format(c=decoded_content))
    return decoded_content


def write_file_download(download_file, http_response, file_size, chunk_size=1024, suppress_status=False):
    """Writes the downloaded file to disk using the response content

    :param download_file: (str) path to write the file download to
    :param http_response: (requests.models.Response) object
    :param file_size: (int) size of the file to download in bytes
    :param chunk_size (int) number of bytes to request in each chunk
    :param suppress_status: (bool) Set true to suppress printing status
    :return: (bool) True if successful, False otherwise
    :raises: None
    """
    log = logging.getLogger(mod_logger + '.write_file_download')
    file_size_dl = 0
    try:
        with open(download_file, 'wb') as f:
            for chunk in http_response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    file_size_dl += len(chunk)
                    if not suppress_status and file_size > 0:
                        status = r"%10d  [%3.2f%%]" % (file_size_dl, file_size_dl * 100. / file_size)
                        status += chr(8)*(len(status)+1)
                        print(status),
    except (requests.exceptions.ConnectionError, requests.exceptions.RequestException, OSError) as exc:
        log.warning('[{n}] error reading content from the response after [{s}] bytes downloaded\n{e}\n{t}'.format(
            n=type(exc).__name__, s=file_size_dl, e=str(exc), t=traceback.format_exc()))
        return False
    log.info('File download of [{s}] bytes completed without error: {f}'.format(s=file_size_dl, f=download_file))
    return True
