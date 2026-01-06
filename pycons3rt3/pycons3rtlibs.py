"""
This module contains a shared library of classes

"""


class HostActionResult(object):

    def __init__(self, dr_id, dr_name, host_id, host_role, action, request_time, num_disks, storage_gb,
                 snapshot_storage_gb=0, gpu_profile='None', gpu_type='None', err_msg='None', result='None'):
        self.dr_id = dr_id
        self.dr_name = dr_name
        self.host_id = host_id
        self.host_role = host_role
        self.action = action
        self.request_time = request_time
        self.num_disks = num_disks
        self.storage_gb = storage_gb
        self.snapshot_storage_gb = snapshot_storage_gb
        self.gpu_profile = gpu_profile
        self.gpu_type = gpu_type
        self.err_msg = err_msg
        self.result = result

    def __str__(self):
        return str(self.dr_id) + ',' + \
               self.dr_name + ',' + \
               str(self.host_id) + ',' + \
               self.host_role + ',' + \
               str(self.num_disks) + ',' + \
               str(self.storage_gb) + ',' + \
               str(self.snapshot_storage_gb) + ',' + \
               str(self.gpu_profile) + ',' + \
               str(self.gpu_type) + ',' + \
               self.request_time + ',' + \
               self.result + ',' + \
               self.err_msg

    @staticmethod
    def get_host_action_result_header():
        return 'DR_ID,DR_Name,HostID,RoleName,NumDisks,StorageGb,SnapshotStorageGb,GpuProfile,GpuType,RequestTime,Result,ErrorMessage'

    def is_fail(self):
        if self.result == 'FAIL':
            return True
        return False

    def is_success(self):
        if self.result == 'OK':
            return True
        return False

    def set_err_msg(self, err_msg):
        self.err_msg = err_msg

    def set_fail(self):
        self.set_result(result='FAIL')
    
    def set_noop(self):
        self.set_result(result='NOOP')

    def set_result(self, result):
        if result not in ['FAIL', 'NOOP', 'OK']:
            raise ValueError('Acceptable result values are: FAIL, NOOP, OK')
        self.result = result

    def set_success(self):
        self.set_result(result='OK')

    def to_dict(self):
        return {
            'dr_id': self.dr_id,
            'dr_name': self.dr_name,
            'host_id': self.host_id,
            'host_role': self.host_role,
            'action': self.action,
            'request_time': self.request_time,
            'num_disks': self.num_disks,
            'storage_gb': self.storage_gb,
            'snapshot_storage_gb': self.snapshot_storage_gb,
            'gpu_profile': self.gpu_profile,
            'gpu_type': self.gpu_type,
            'err_msg': self.err_msg,
            'result': self.result
        }


class RestUser(object):

    def __init__(self, rest_api_url, token, project=None, cert_file_path=None, key_file_path=None, username=None,
                 cert_bundle=None, site_default_project=False):
        self.rest_api_url = rest_api_url
        self.token = token
        self.project_name = project
        self.cert_file_path = cert_file_path
        self.key_file_path = key_file_path
        self.username = username
        self.cert_bundle = cert_bundle
        self.site_default_project = site_default_project

    def __str__(self):
        user_str = 'CONS3RT user for site [{s}] in project [{p}]'.format(s=self.rest_api_url, p=self.project_name)
        if self.cert_file_path:
            user_str += ', using cert [{c}]'.format(c=self.cert_file_path)
            if self.key_file_path:
                user_str += ' and key [{k}]'.format(k=self.key_file_path)
        elif self.username:
            user_str += ', using username [{u}]'.format(u=self.username)
        if self.cert_bundle:
            if isinstance(self.cert_bundle, str):
                user_str += ', using CA cert bundle [{b}]'.format(b=self.cert_bundle)
        if self.site_default_project:
            user_str += ' (default)'
        return user_str
