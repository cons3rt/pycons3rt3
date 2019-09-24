#!/usr/bin/env python

import logging
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
            response = requests.get(url, headers=headers, cert=rest_user.cert_file_path)
        except RequestException as exc:
            raise Cons3rtClientError(str(exc)) from exc
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP GET to URL: {u}'.format(u=url)
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
                response = requests.delete(url, headers=headers, cert=rest_user.cert_file_path)
            else:
                response = requests.delete(
                    url, headers=headers, data=content, cert=rest_user.cert_file_path)
        except RequestException as exc:
            raise Cons3rtClientError(str(exc)) from exc
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP GET to URL: {u}\n{e}'.format(
                u=url, e=str(exc))
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
                msg = 'Unable to read contents of file: {f}\n{e}'.format(
                    f=content_file, e=str(exc))
                raise Cons3rtClientError(msg) from exc
        # Otherwise use data provided as content
        elif content_data:
            content = content_data

        # Add content type if content was provided
        if content:
            headers['Content-Type'] = '{t}'.format(t=content_type)

        # Make the put request
        try:
            response = requests.post(url, headers=headers, data=content, cert=rest_user.cert_file_path)
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP POST to URL: {u}\n{e}'.format(
                u=url, e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except requests.ConnectionError as exc:
            msg = 'Connection error encountered making HTTP POST:\n{e}'.format(
                e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except requests.Timeout as exc:
            msg = 'HTTP POST to URL {u} timed out\n{e}'.format(u=url, e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except RequestException as exc:
            msg = 'There was a problem making an HTTP POST to URL: {u}\n{e}'.format(
                u=url, e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except Exception as exc:
            msg = 'Generic error caught making an HTTP POST to URL: {u}\n{e}'.format(
                u=url, e=str(exc))
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
                msg = 'Unable to read contents of file: {f}\n{e}'.format(
                    f=content_file, e=str(exc))
                raise Cons3rtClientError(msg) from exc
        # Otherwise use data provided as content
        elif content_data:
            content = content_data

        # Add content type if content was provided
        if content:
            headers['Content-Type'] = '{t}'.format(t=content_type)

        # Make the put request
        try:
            response = requests.put(url, headers=headers, data=content, cert=rest_user.cert_file_path)
        except SSLError as exc:
            msg = 'There was an SSL error making an HTTP PUT to URL: {u}\n{e}'.format(
                u=url, e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except requests.ConnectionError as exc:
            msg = 'Connection error encountered making HTTP Put:\n{e}'.format(
                e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except requests.Timeout as exc:
            msg = 'HTTP put to URL {u} timed out\n{e}'.format(u=url, e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except RequestException as exc:
            msg = 'There was a problem making an HTTP put to URL: {u}\n{e}'.format(
                u=url, e=str(exc))
            raise Cons3rtClientError(msg) from exc
        except Exception as exc:
            msg = 'Generic error caught making an HTTP put to URL: {u}\n{e}'.format(
                u=url, e=str(exc))
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
                response = s.send(prepped, cert=rest_user.cert_file_path)
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
        log.debug('Parsing response with content: {s}'.format(s=response.content))
        if response.status_code == requests.codes.ok:
            log.debug('Received an OK HTTP Response Code!')
            return response.content
        elif response.status_code == 202:
            log.debug('Received an ACCEPTED HTTP Response Code!')
            return response.content
        else:
            msg = 'Received HTTP code [{n}] with headers:\n{h}'.format(
                n=str(response.status_code), h=response.headers)
            if response.content:
                msg += '\nand content:\n{c}'.format(c=response.content)
            log.warning(msg)
            raise Cons3rtClientError(msg)
