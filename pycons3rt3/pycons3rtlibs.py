"""
This module contains a shared library of classes
"""


class RestUser(object):

    def __init__(self, rest_api_url, token, project=None, cert_file_path=None, key_file_path=None, username=None,
                 cert_bundle=None):
        self.rest_api_url = rest_api_url
        self.token = token
        self.project_name = project
        self.cert_file_path = cert_file_path
        self.key_file_path = key_file_path
        self.username = username
        self.cert_bundle = cert_bundle

    def __str__(self):
        base_str = 'CONS3RT user for site [{s}] in project: {p}'.format(s=self.rest_api_url, p=self.project_name)
        if self.cert_file_path:
            return base_str + ', using cert auth: {c}'.format(c=self.cert_file_path)
        elif self.username:
            return base_str + ', using username auth: {u}'.format(u=self.username)
        else:
            return base_str
