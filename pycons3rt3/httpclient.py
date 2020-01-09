#!/usr/bin/env python

import logging
import os
import sys
import time

from requests_toolbelt import MultipartEncoder

import requests
from requests.exceptions import RequestException, SSLError

from .logify import Logify
from .exceptions import Cons3rtClientError

# Set up logger name for this module
mod_logger = Logify.get_name() + '.httpclient'


class Client:

    def __init__(self, base):
        self.base = base

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
            response = requests.get(url, headers=headers, cert=rest_user.cert_file_path, verify=rest_user.cert_bundle)
        except RequestException as exc:
            raise Cons3rtClientError(str(exc)) from exc
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP GET to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        return response

    def http_get_download(self, rest_user, target):
        """Runs an HTTP GET request to the CONS3RT ReST API

        :param rest_user: (RestUser) user info
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
            response = requests.get(url, headers=headers, cert=rest_user.cert_file_path, verify=rest_user.cert_bundle)
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP GET to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except requests.ConnectionError as exc:
            msg = 'Connection error encountered making HTTP GET to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except requests.Timeout as exc:
            msg = 'There was a timeout making an HTTP GET to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except RequestException as exc:
            msg = 'There was a general RequestException making an HTTP GET to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except Exception as exc:
            msg = 'Generic error caught making an HTTP GET to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        return response

    def http_delete(self, rest_user, target, content=None, keep_alive=False):
        self.validate_target(target)

        url = self.base + target

        headers = self.get_auth_headers(rest_user=rest_user)
        headers['Content-Type'] = 'application/json'

        if keep_alive:
            headers['Connection'] = 'Keep-Alive'

        try:
            if content is None:
                response = requests.delete(
                    url, headers=headers, cert=rest_user.cert_file_path, verify=rest_user.cert_bundle)
            else:
                response = requests.delete(
                    url, headers=headers, data=content, cert=rest_user.cert_file_path, verify=rest_user.cert_bundle)
        except RequestException as exc:
            raise Cons3rtClientError(str(exc)) from exc
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP GET to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        return response

    def http_post(self, rest_user, target, content_data=None, content_file=None, content_type='application/json'):
        """Makes an HTTP Post to the requested URL

        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_file: (str) path to the content file
        :param content_data: (str) body data
        :param content_type: (str) Content-Type, default is application/json
        :return: (str) HTTP Response or None
        :raises: Cons3rtClientError
        """
        self.validate_target(target)
        url = self.base + target

        headers = self.get_auth_headers(rest_user=rest_user)
        headers['Content-Type'] = '{t}'.format(t=content_type)
        content = None

        # Read data from the file if provided
        if content_file:
            try:
                with open(content_file, 'r') as f:
                    content = f.read()
            except (OSError, IOError) as exc:
                msg = 'Unable to read contents of file: {f}'.format(f=content_file)
                raise Cons3rtClientError(msg) from exc
        # Otherwise use data provided as content
        elif content_data:
            content = content_data

        # Add content type if content was provided
        if content:
            headers['Content-Type'] = '{t}'.format(t=content_type)

        # Make the put request
        try:
            response = requests.post(url, headers=headers, data=content, cert=rest_user.cert_file_path,
                                     verify=rest_user.cert_bundle)
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP POST to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except requests.ConnectionError as exc:
            msg = 'Connection error encountered making HTTP POST'
            raise Cons3rtClientError(msg) from exc
        except requests.Timeout as exc:
            msg = 'HTTP POST to URL {u} timed out'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except RequestException as exc:
            msg = 'There was a problem making an HTTP POST to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except Exception as exc:
            msg = 'Generic error caught making an HTTP POST to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        return response

    def http_put(self, rest_user, target, content_data=None, content_file=None, content_type='application/json'):
        """Makes an HTTP Post to the requested URL

        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_data: (str) body data
        :param content_file: (str) path to the content file containing body data
        :param content_type: (str) Content-Type, default is application/json
        :return: (str) HTTP Response or None
        :raises: Cons3rtClientError
        """
        self.validate_target(target)
        url = self.base + target
        headers = self.get_auth_headers(rest_user=rest_user)
        content = None

        # Read data from the file if provided
        if content_file:
            try:
                with open(content_file, 'r') as f:
                    content = f.read()
            except (OSError, IOError) as exc:
                msg = 'Unable to read contents of file: {f}'.format(f=content_file)
                raise Cons3rtClientError(msg) from exc
        # Otherwise use data provided as content
        elif content_data:
            content = content_data

        # Add content type if content was provided
        if content:
            headers['Content-Type'] = '{t}'.format(t=content_type)

        # Make the put request
        try:
            response = requests.put(url, headers=headers, data=content, cert=rest_user.cert_file_path,
                                    verify=rest_user.cert_bundle)
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP PUT to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except requests.ConnectionError as exc:
            msg = 'Connection error encountered making HTTP PUT'
            raise Cons3rtClientError(msg) from exc
        except requests.Timeout as exc:
            msg = 'HTTP put to URL {u} timed out'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except RequestException as exc:
            msg = 'There was a problem making an HTTP put to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        except Exception as exc:
            msg = 'Generic error caught making an HTTP put to URL: {u}'.format(u=url)
            raise Cons3rtClientError(msg) from exc
        return response

    def http_multipart(self, method, rest_user, target, content_file):
        """Makes an HTTP Multipart request to upload a file

        :param method: (str) PUT or POST
        :param rest_user: (RestUser) user info
        :param target: (str) ReST API target URL
        :param content_file: (str) path to the content file
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

        # Set headers
        headers = self.get_auth_headers(rest_user=rest_user)
        headers['Accept'] = 'application/json'
        headers['Connection'] = 'Keep-Alive'
        headers['Expect'] = '100-continue'

        # Open the content_file to create the multipart encoder
        start_time = time.time()
        response = None
        with open(content_file, 'rb') as f:

            # Create the MultipartEncoder (thanks requests_toolbelt!)
            form = MultipartEncoder({
                "file": ("asset.zip", f, "application/octet-stream"),
                "filename": "asset.zip"
            })

            # Add the Content-Type
            headers["Content-Type"] = form.content_type

            # Create the request
            s = requests.Session()
            req = requests.Request(method, url, data=form, headers=headers)
            prepped = req.prepare()
            log.info('Request URL: {u}'.format(u=url))
            log.info('Prepped headers: {h}'.format(h=prepped.headers))
            log.info('Making request with method: [{m}]'.format(m=method))

            # Send the request
            try:
                response = s.send(prepped, cert=rest_user.cert_file_path, verify=rest_user.cert_bundle)
            except SSLError:
                self.__http_exception__(
                    exc=sys.exc_info(),
                    msg_part='There was an SSL error making an HTTP {m} to URL: {u}'.format(m=method, u=url),
                    start_time=start_time)
            except requests.ConnectionError:
                self.__http_exception__(
                    exc=sys.exc_info(),
                    msg_part='Connection error encountered making HTTP {m}'.format(m=method),
                    start_time=start_time)
            except requests.Timeout:
                self.__http_exception__(
                    exc=sys.exc_info(),
                    msg_part='HTTP {m} to URL {u} timed out'.format(m=method, u=url),
                    start_time=start_time)
            except RequestException:
                self.__http_exception__(
                    exc=sys.exc_info(),
                    msg_part='There was a problem making an HTTP {m} to URL: {u}'.format(m=method, u=url),
                    start_time=start_time)
        complete_time = time.time()
        log.info('Request completed in {t} seconds'.format(t=str(round(complete_time - start_time, 2))))
        return response

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

    def parse_response(self, response):
        log = logging.getLogger(self.cls_logger + '.parse_response')

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
            msg = 'Received HTTP code [{n}] with headers:\n{h}'.format(
                n=str(response.status_code), h=response.headers)
            if decoded_content:
                msg += '\nand content:\n{c}'.format(c=decoded_content)
            log.warning(msg)
            raise Cons3rtClientError(msg)

        # Return the decoded content
        if response.status_code == requests.codes.ok:
            log.debug('Received an OK HTTP Response Code')
        elif response.status_code == 202:
            log.debug('Received an ACCEPTED HTTP Response Code (202)')
        log.debug('Parsed decoded content: {c}'.format(c=decoded_content))
        return decoded_content

    def http_download(self, rest_user, target, download_file, overwrite=True, suppress_status=True):
        """Runs an HTTP GET request to the CONS3RT ReST API

        :param rest_user: (RestUser) user info
        :param target: (str) URL
        :param download_file (str) destination file path
        :param overwrite (bool) set True to overwrite the existing file
        :param suppress_status: (bool) Set to True to suppress printing download status
        :return: (str) path to the downloaded file
        """
        log = logging.getLogger(self.cls_logger + '.http_download')
        log.info('Attempting to download target [{t}] to: {d}'.format(t=target, d=download_file))
        
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

            log.info('Attempt # {n} of {m} to query target URL: {u}'.format(n=try_num, m=max_retries, u=target))
            try:
                response = self.http_get_download(rest_user=rest_user, target=target)
            except Cons3rtClientError as exc:
                msg = 'There was a problem querying target with GET: {u}'.format(u=target)
                raise Cons3rtClientError(msg) from exc
    
            # Attempt to get the content-length
            file_size = 0
            try:
                file_size = int(response.headers['Content-Length'])
            except(KeyError, ValueError):
                log.debug('Could not get Content-Length, suppressing download status...')
                suppress_status = True
            else:
                log.info('Download file size: {s}'.format(s=file_size))

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
            chunk_size = 1024
            file_size_dl = 0
            try:
                with open(download_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            file_size_dl += len(chunk)
                            status = r"%10d  [%3.2f%%]" % (file_size_dl, file_size_dl * 100. / file_size)
                            status += chr(8)*(len(status)+1)
                            if not suppress_status:
                                print(status),
            except(requests.exceptions.ConnectionError, requests.exceptions.RequestException, OSError) as exc:
                dl_err = 'There was an error reading content from the response. Downloaded ' \
                         'size: {s}.\n{e}'.format(s=file_size_dl, t=retry_sec, e=str(exc))
                failed_attempt = True
                log.warning(dl_err)
                if try_num < max_retries:
                    log.info('Retrying download in {t} sec...'.format(t=retry_sec))
                    time.sleep(retry_sec)
            else:
                log.info('File download of size {s} completed without error: {f}'.format(
                    s=file_size_dl, f=download_file))
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
