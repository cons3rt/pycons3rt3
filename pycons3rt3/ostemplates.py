#!/usr/bin/env python

from .exceptions import InvalidOperatingSystemTemplate
from .logify import Logify


# Set up logger name for this module
mod_logger = Logify.get_name() + '.ostemplates'


class OperatingSystemType(object):

    operating_system_types = [
        'AMAZON_LINUX_LATEST_X64',
        'AMAZON_LINUX_2_LATEST_X64',
        'CENTOS_6_X64',
        'CENTOS_6_X86',
        'CENTOS_7_X64',
        'CENTOS_8_X64',
        'CORE_OS_1221_X64',
        'F5_BIGIP_X64',
        'FORTISIEM',
        'PALO_ALTO_NETWORKS_PAN_OS_X64',
        'FEDORA_23_X64',
        'GENERIC_LINUX_X64',
        'GENERIC_WINDOWS_X64',
        'KALI_ROLLING_X64',
        'ORACLE_LINUX_6_X64',
        'ORACLE_LINUX_7_X64',
        'ORACLE_LINUX_8_X64',
        'OS_X_10',
        'OS_X_11',
        'RASPBIAN',
        'RHEL_5_X64',
        'RHEL_5_X86',
        'RHEL_6_X64',
        'RHEL_6_X86',
        'RHEL_7_ATOMIC_HOST',
        'RHEL_7_PPCLE',
        'RHEL_7_X64',
        'RHEL_8_X64',
        'SOLARIS_11_X64',
        'UBUNTU_12_X64',
        'UBUNTU_14_X64',
        'UBUNTU_16_X64',
        'UBUNTU_18_X64',
        'UBUNTU_20_X64',
        'UBUNTU_CORE',
        'VYOS_1_1_X64',
        'VYOS_1_2_X64',
        'VYOS_1_3_X64',
        'VYOS_ROLLING_X64',
        'WINDOWS_10_X64',
        'WINDOWS_7_X64',
        'WINDOWS_7_X86',
        'WINDOWS_8_X64',
        'WINDOWS_SERVER_2008_R2_X64',
        'WINDOWS_SERVER_2008_X64',
        'WINDOWS_SERVER_2012_R2_X64',
        'WINDOWS_SERVER_2012_X64',
        'WINDOWS_SERVER_2016_X64',
        'WINDOWS_SERVER_2019_X64',
        'WINDOWS_SERVER_2019_CORE_X64',
        'WINDOWS_XP_X86'
    ]

    operating_system_types_str = ','.join(operating_system_types)

    yum_package_distros = [
        'AMAZON_LINUX_LATEST_X64',
        'AMAZON_LINUX_2_LATEST_X64',
        'CENTOS_6_X64',
        'CENTOS_6_X86',
        'CENTOS_7_X64',
        'FEDORA_23_X64',
        'ORACLE_LINUX_6_X64',
        'ORACLE_LINUX_7_X64',
        'RHEL_5_X64',
        'RHEL_6_X64',
        'RHEL_6_X86',
        'RHEL_7_PPCLE',
        'RHEL_7_X64',
        'F5_BIGIP_X64',
        'FORTISIEM',
        'PALO_ALTO_NETWORKS_PAN_OS_X64'
    ]

    docker_package_distros = [
        'CORE_OS_1221_X64'
    ]

    apt_package_distros = [
        'KALI_ROLLING_X64',
        'RASPBIAN',
        'UBUNTU_12_X64',
        'UBUNTU_14_X64',
        'UBUNTU_16_X64',
        'UBUNTU_18_X64',
        'UBUNTU_20_X64'
    ]

    dnf_package_distros = [
        'CENTOS_8_X64',
        'FEDORA_23_X64',
        'ORACLE_LINUX_8_X64',
        'RHEL_8_X64'
    ]

    app_store_package_distros = [
        'OS_X_10',
        'OS_X_11'
    ]

    pkgadd_package_distros = [
        'SOLARIS_11_X64'
    ]

    snap_package_distros = [
        'UBUNTU_CORE'
    ]

    systemd_service_distros = [
        'AMAZON_LINUX_2_LATEST_X64',
        'CENTOS_7_X64',
        'CENTOS_8_X64',
        'FEDORA_23_X64',
        'ORACLE_LINUX_7_X64',
        'ORACLE_LINUX_8_X64',
        'RASPBIAN',
        'RHEL_7_PPCLE',
        'RHEL_7_X64',
        'RHEL_8_X64',
        'SOLARIS_11_X64',
        'UBUNTU_16_X64',
        'UBUNTU_18_X64',
        'UBUNTU_20_X64'
    ]

    initd_service_distros = [
        'AMAZON_LINUX_LATEST_X64',
        'CENTOS_6_X64',
        'CENTOS_6_X86',
        'F5_BIGIP_X64',
        'FORTISIEM',
        'ORACLE_LINUX_6_X64',
        'PALO_ALTO_NETWORKS_PAN_OS_X64',
        'RHEL_5_X64',
        'RHEL_5_X86',
        'RHEL_6_X64',
        'RHEL_6_X86',
        'RHEL_7_ATOMIC_HOST'
    ]

    upstart_service_distros = [
        'KALI_ROLLING_X64',
        'UBUNTU_14_X64'
    ]

    launchd_service_distros = [
        'OS_X_10',
        'OS_X_11'
    ]

    update_rc_service_distros = [
        'VYOS_1_1_X64',
        'VYOS_1_2_X64',
        'VYOS_1_3_X64',
        'VYOS_ROLLING_X64'
    ]

    powershell_v1 = [
        'GENERIC_WINDOWS_X64',
        'WINDOWS_SERVER_2008_X64'
    ]

    powershell_v2 = [
        'WINDOWS_7_X64',
        'WINDOWS_7_X86',
        'WINDOWS_SERVER_2008_R2_X64'
    ]

    powershell_v3 = [
        'WINDOWS_8_X64',
        'WINDOWS_SERVER_2012_X64'
    ]

    powershell_v4 = [
        'WINDOWS_SERVER_2012_R2_X64'
    ]

    powershell_v5 = [
        'WINDOWS_10_X64',
        'WINDOWS_SERVER_2016_X64',
        'WINDOWS_SERVER_2019_X64',
        'WINDOWS_SERVER_2019_CORE_X64'
    ]

    remote_access_rdp = [
        'WINDOWS_10_X64',
        'WINDOWS_7_X64',
        'WINDOWS_7_X86',
        'WINDOWS_8_X64',
        'WINDOWS_SERVER_2008_R2_X64',
        'WINDOWS_SERVER_2008_X64',
        'WINDOWS_SERVER_2012_R2_X64',
        'WINDOWS_SERVER_2012_X64',
        'WINDOWS_SERVER_2016_X64',
        'WINDOWS_SERVER_2019_X64',
        'WINDOWS_SERVER_2019_CORE_X64',
        'WINDOWS_XP_X86',
        'GENERIC_WINDOWS_X64'
    ]

    remote_access_ssh = [
        'AMAZON_LINUX_LATEST_X64',
        'AMAZON_LINUX_2_LATEST_X64',
        'CENTOS_6_X64',
        'CENTOS_6_X86',
        'CENTOS_7_X64',
        'CENTOS_8_X64',
        'CORE_OS_1221_X64',
        'F5_BIGIP_X64',
        'FORTISIEM',
        'PALO_ALTO_NETWORKS_PAN_OS_X64',
        'FEDORA_23_X64',
        'GENERIC_LINUX_X64',
        'KALI_ROLLING_X64',
        'ORACLE_LINUX_6_X64',
        'ORACLE_LINUX_7_X64',
        'ORACLE_LINUX_8_X64',
        'OS_X_10',
        'OS_X_11',
        'RASPBIAN',
        'RHEL_5_X64',
        'RHEL_5_X86',
        'RHEL_6_X64',
        'RHEL_6_X86',
        'RHEL_7_ATOMIC_HOST',
        'RHEL_7_PPCLE',
        'RHEL_7_X64',
        'RHEL_8_X64',
        'SOLARIS_11_X64',
        'UBUNTU_12_X64',
        'UBUNTU_14_X64',
        'UBUNTU_16_X64',
        'UBUNTU_18_X64',
        'UBUNTU_20_X64',
        'UBUNTU_CORE',
        'VYOS_1_1_X64',
        'VYOS_1_2_X64',
        'VYOS_1_3_X64',
        'VYOS_ROLLING_X64'
    ]

    remote_access_vnc = [
        'AMAZON_LINUX_LATEST_X64',
        'AMAZON_LINUX_2_LATEST_X64',
        'CENTOS_6_X64',
        'CENTOS_6_X86',
        'CENTOS_7_X64',
        'CENTOS_8_X64',
        'CORE_OS_1221_X64',
        'F5_BIGIP_X64',
        'FORTISIEM',
        'PALO_ALTO_NETWORKS_PAN_OS_X64',
        'FEDORA_23_X64',
        'GENERIC_LINUX_X64',
        'KALI_ROLLING_X64',
        'ORACLE_LINUX_6_X64',
        'ORACLE_LINUX_7_X64',
        'ORACLE_LINUX_8_X64',
        'OS_X_10',
        'OS_X_11',
        'RASPBIAN',
        'RHEL_5_X64',
        'RHEL_5_X86',
        'RHEL_6_X64',
        'RHEL_6_X86',
        'RHEL_7_ATOMIC_HOST',
        'RHEL_7_PPCLE',
        'RHEL_7_X64',
        'RHEL_8_X64',
        'SOLARIS_11_X64',
        'UBUNTU_12_X64',
        'UBUNTU_14_X64',
        'UBUNTU_16_X64',
        'UBUNTU_18_X64',
        'UBUNTU_20_X64',
        'UBUNTU_CORE',
        'VYOS_1_1_X64',
        'VYOS_1_2_X64',
        'VYOS_1_3_X64',
        'VYOS_ROLLING_X64'
    ]

    container_capable = [
        'AMAZON_LINUX_LATEST_X64',
        'AMAZON_LINUX_2_LATEST_X64',
        'CENTOS_7_X64',
        'CENTOS_8_X64',
        'CORE_OS_1221_X64',
        'ORACLE_LINUX_7_X64',
        'RHEL_7_ATOMIC_HOST',
        'RHEL_7_PPCLE',
        'RHEL_7_X64',
        'RHEL_8_X64',
        'UBUNTU_16_X64',
        'UBUNTU_18_X64',
        'UBUNTU_20_X64'
    ]

    @staticmethod
    def get_linux_package_manager(operating_system_type):
        if operating_system_type in OperatingSystemType.yum_package_distros:
            return 'YUM'
        elif operating_system_type in OperatingSystemType.apt_package_distros:
            return 'APT_GET'
        elif operating_system_type in OperatingSystemType.docker_package_distros:
            return 'DOCKER'
        elif operating_system_type in OperatingSystemType.dnf_package_distros:
            return 'DNF'
        elif operating_system_type in OperatingSystemType.app_store_package_distros:
            return 'APP_STORE'
        elif operating_system_type in OperatingSystemType.pkgadd_package_distros:
            return 'PKGADD'
        elif operating_system_type in OperatingSystemType.snap_package_distros:
            return 'SNAP'
        else:
            return 'NONE'

    @staticmethod
    def get_linux_service_manager(operating_system_type):
        if operating_system_type in OperatingSystemType.systemd_service_distros:
            return 'SYSTEMD'
        elif operating_system_type in OperatingSystemType.initd_service_distros:
            return 'INITD'
        elif operating_system_type in OperatingSystemType.launchd_service_distros:
            return 'LAUNCHD'
        elif operating_system_type in OperatingSystemType.update_rc_service_distros:
            return 'UPDATE_RC'
        elif operating_system_type in OperatingSystemType.upstart_service_distros:
            return 'UPSTART'
        elif 'WINDOWS' in operating_system_type:
            return 'WINDOWS'
        else:
            return 'UNKNOWN'

    @staticmethod
    def get_powershell_version(operating_system_type):
        if operating_system_type in OperatingSystemType.powershell_v1:
            return 'POWERSHELL_1_0'
        elif operating_system_type in OperatingSystemType.powershell_v2:
            return 'POWERSHELL_2_0'
        elif operating_system_type in OperatingSystemType.powershell_v3:
            return 'POWERSHELL_3_0'
        elif operating_system_type in OperatingSystemType.powershell_v4:
            return 'POWERSHELL_4_0'
        elif operating_system_type in OperatingSystemType.powershell_v5:
            return 'POWERSHELL_5_0'
        else:
            return 'NONE'

    @staticmethod
    def needs_remote_access_ssh(operating_system_type):
        return operating_system_type in OperatingSystemType.remote_access_ssh

    @staticmethod
    def needs_remote_access_vnc(operating_system_type):
        return operating_system_type in OperatingSystemType.remote_access_vnc

    @staticmethod
    def needs_remote_access_rdp(operating_system_type):
        return operating_system_type in OperatingSystemType.remote_access_rdp

    @staticmethod
    def get_container_capable(operating_system_type):
        return operating_system_type in OperatingSystemType.container_capable

    @staticmethod
    def guess_os_type(template_name):
        template_name = template_name.lower()
        if 'amazon' in template_name:
            if '2' in template_name:
                return 'AMAZON_LINUX_2_LATEST_X64'
            else:
                return 'AMAZON_LINUX_LATEST_X64'
        if 'atomic' in template_name:
            return 'RHEL_7_ATOMIC_HOST'
        if 'coreos' in template_name or 'core os' in template_name:
            return 'CORE_OS_1221_X64'
        if 'kali' in template_name:
            return 'KALI_ROLLING_X64'
        if 'palo' in template_name or 'alto' in template_name:
            return 'PALO_ALTO_NETWORKS_PAN_OS_X64'
        if 'forti' in template_name:
            return 'FORTISIEM'
        if 'big' in template_name and 'ip' in template_name:
            return 'F5_BIGIP_X64'
        if 'fedora' in template_name:
            return 'FEDORA_23_X64'
        if 'rasp' in template_name:
            return 'RASPBIAN'
        if 'redhat-5' in template_name or 'rhel5' in template_name or 'rhel-5' in template_name:
            return 'RHEL_5_X86'
        if 'redhat-6' in template_name or 'rhel6' in template_name or 'rhel-6' in template_name:
            if 'x86' in template_name:
                return 'RHEL_6_X86'
            else:
                return 'RHEL_6_X64'
        if 'redhat-7' in template_name or 'rhel7' in template_name or 'rhel-7' in template_name:
            if 'ppc' in template_name:
                return 'RHEL_7_PPCLE'
            else:
                return 'RHEL_7_X64'
        if 'redhat-8' in template_name or 'rhel8' in template_name or 'rhel-8' in template_name:
            return 'RHEL_8_X64'
        if 'centos-6' in template_name or 'centos6' in template_name:
            if 'x86' in template_name:
                return 'CENTOS_6_X86'
            else:
                return 'CENTOS_6_X64'
        if 'CentOS 6' in template_name:
            return 'CENTOS_6_X64'
        if 'centos-7' in template_name or 'centos7' in template_name:
            return 'CENTOS_7_X64'
        if 'centos-8' in template_name or 'centos8' in template_name:
            return 'CENTOS_8_X64'
        if 'ubuntu-14' in template_name or 'ubuntu14' in template_name:
            return 'UBUNTU_14_X64'
        if 'ubuntu-16' in template_name or 'ubuntu16' in template_name:
            return 'UBUNTU_16_X64'
        if 'ubuntu-18' in template_name or 'ubuntu18' in template_name:
            return 'UBUNTU_18_X64'
        if 'ubuntu-20' in template_name or 'ubuntu20' in template_name:
            return 'UBUNTU_20_X64'
        if 'ubuntu' in template_name:
            if 'core' in template_name:
                return 'UBUNTU_CORE'
        if 'oracle-6' in template_name or 'oracle6' in template_name:
            return 'ORACLE_LINUX_6_X64'
        if 'oracle-7' in template_name or 'oracle7' in template_name:
            return 'ORACLE_LINUX_7_X64'
        if 'oracle-8' in template_name or 'oracle8' in template_name:
            return 'ORACLE_LINUX_8_X64'
        if 'vyos-rolling' in template_name:
            return 'VYOS_ROLLING_X64'
        if 'vyos-1.3' in template_name or 'vyos13' in template_name:
            return 'VYOS_1_3_X64'
        if 'vyos-1.2' in template_name or 'vyos12' in template_name:
            return 'VYOS_1_2_X64'
        if 'vyos-1.1' in template_name or 'vyos11' in template_name:
            return 'VYOS_1_1_X64'
        if 'windows' in template_name or 'win' in template_name:
            if '2008' in template_name or '2k8' in template_name:
                if 'r2' in template_name:
                    return 'WINDOWS_SERVER_2008_R2_X64'
                else:
                    return 'WINDOWS_SERVER_2008_X64'
            if '2012' in template_name or '2k12' in template_name:
                if 'r2' in template_name:
                    return 'WINDOWS_SERVER_2012_R2_X64'
                else:
                    return 'WINDOWS_SERVER_2012_X64'
            if '2016' in template_name or '2k16' in template_name:
                return 'WINDOWS_SERVER_2016_X64'
            if '2019' in template_name or '2k19' in template_name:
                if 'core' in template_name:
                    return 'WINDOWS_SERVER_2019_CORE_X64'
                else:
                    return 'WINDOWS_SERVER_2019_X64'
            if 'win10' in template_name or 'windows-10' in template_name:
                return 'WINDOWS_10_X64'
            if 'win7' in template_name or 'windows-7' in template_name:
                if 'x86' in template_name:
                    return 'WINDOWS_7_X86'
                else:
                    return 'WINDOWS_7_X64'
            if 'win8' in template_name or 'windows-8' in template_name:
                return 'WINDOWS_8_X64'
            if 'xp' in template_name:
                return 'WINDOWS_XP_X86'
            return 'GENERIC_WINDOWS_X64'
        if 'linux' in template_name:
            return 'GENERIC_LINUX_X64'


class OperatingSystemTemplate(object):

    def __init__(self, template_name, operating_system_type):
        self.template_name = template_name
        self.operating_system_type = operating_system_type
        self.registration_data = {}
        self.required_args = [
            'cons3rt_agent_installed', 'container_capable', 'max_cpus', 'max_ram_mb'
        ]
        self.root_disk_size = 102400
        self.additional_disks = []
        self.disks = []
        self.remote_access_templates = []

    def is_valid_operating_system_type(self):
        return self.operating_system_type in OperatingSystemType.operating_system_types

    def generate_registration_data(self, **kwargs):
        """Generates a dict of template registration data

        :param kwargs: (dict)
        :return: (dict) template registration data
        :raises: InvalidOperatingSystemTemplate
        """
        self.validate_args(kwargs)
        self.determine_remote_access_templates()

        # Build the template registration data
        template_data = {
            'displayName': self.template_name,
            'virtRealmTemplateName': self.template_name,
            'operatingSystem': self.operating_system_type,
            'cons3rtAgentInstalled': kwargs['cons3rt_agent_installed'],
            'containerCapable': kwargs['container_capable'],
            'maxNumCpus': kwargs['max_cpus'],
            'maxRamInMegabytes': kwargs['max_ram_mb'],
            'disks': self.disks
        }

        # Add registration data that can be enumerated
        template_data['packageManagementType'] = OperatingSystemType.get_linux_package_manager(
            self.operating_system_type)
        template_data['powerShellVersion'] = OperatingSystemType.get_powershell_version(
            self.operating_system_type)
        template_data['serviceManagementType'] = OperatingSystemType.get_linux_service_manager(
            self.operating_system_type)

        # Add remote access data
        template_data['remoteAccessTemplates'] = self.remote_access_templates

        # Add container capability
        template_data['containerCapable'] = OperatingSystemType.get_container_capable(
            self.operating_system_type)

        # Update optional values from kwargs
        for kwarg, value in kwargs.items():
            if value is None:
                continue
            if kwarg == 'display_name':
                template_data['displayName'] = value
            elif kwarg == 'default_password':
                template_data['defaultPassword'] = value
            elif kwarg == 'default_username':
                template_data['defaultUsername'] = value
            elif kwarg == 'license_str':
                template_data['license'] = value
            elif kwarg == 'note':
                template_data['note'] = value
            elif kwarg == 'power_on_delay_override':
                template_data['powerOnDelayOverride'] = value
            elif kwarg == 'linux_package_manager':
                template_data['packageManagementType'] = value
            elif kwarg == 'powershell_version':
                template_data['powerShellVersion'] = value
            elif kwarg == 'linux_service_management':
                template_data['serviceManagementType'] = value
        return template_data

    def validate_args(self, kwargs):
        """Validates the provided args

        :param kwargs: (dict)
        :return: None
        :raises: InvalidOperatingSystemTemplate
        """
        if not self.is_valid_operating_system_type():
            msg = 'OS type is not valid: {t}, must be one of: {v}'.format(
                t=self.operating_system_type, v=OperatingSystemType.operating_system_types_str)
            raise InvalidOperatingSystemTemplate(msg)

        # Ensure required data is present
        missing_required_args = []
        for required_arg in self.required_args:
            if required_arg not in kwargs.keys():
                missing_required_args.append(required_arg)
        if len(missing_required_args) > 0:
            msg = 'Missing required args: {a}'.format(a=','.join(missing_required_args))
            raise InvalidOperatingSystemTemplate(msg)

        arg_bools = ['cons3rt_agent_installed', 'container_capable']
        for arg_bool in arg_bools:
            if not kwargs[arg_bool]:
                continue
            if arg_bool in kwargs.keys():
                if not isinstance(kwargs[arg_bool], bool):
                    msg = '{b} must be a bool, found: {t}'.format(b=arg_bool, t=type(kwargs[arg_bool]).__name__)
                    raise InvalidOperatingSystemTemplate(msg)

        arg_ints = ['max_cpus', 'max_ram_mb', 'power_on_delay_override']
        for arg_int in arg_ints:
            if not kwargs[arg_int]:
                continue
            if arg_int in kwargs.keys():
                if not isinstance(kwargs[arg_int], int):
                    msg = '{b} must be an int, found: {t}'.format(b=arg_int, t=type(kwargs[arg_int]).__name__)
                    raise InvalidOperatingSystemTemplate(msg)

        arg_strs = ['display_name', 'default_password', 'default_username', 'license_str', 'note',
                    'linux_package_manager', 'powershell_version', 'linux_service_management']
        for arg_str in arg_strs:
            if not kwargs[arg_str]:
                continue
            if arg_str in kwargs.keys():
                if not isinstance(kwargs[arg_str], str):
                    msg = '{b} must be a str, found: {t}'.format(b=arg_str, t=type(kwargs[arg_str]).__name__)
                    raise InvalidOperatingSystemTemplate(msg)

        self.validate_disks(kwargs)

    def validate_disks(self, kwargs):
        if 'disks' not in kwargs.keys():
            self.disks = [
                {
                    'capacityInMegabytes': self.root_disk_size,
                    'isAdditionalDisk': False,
                    'isBootDisk': True
                }
            ]
            return

        if not isinstance(kwargs['disks'], list):
            msg = 'disks must be a list, found: {t}'.format(t=type(kwargs['disks']).__name__)
            raise InvalidOperatingSystemTemplate(msg)

        has_boot_disk = False
        for disk in kwargs['disks']:
            if 'capacityInMegabytes' not in disk.keys():
                msg = 'Additional disk missing capacityInMegabytes data: {d}'.format(d=str(disk))
                raise InvalidOperatingSystemTemplate(msg)
            if 'isBootDisk' in disk.keys():
                if not isinstance(disk['isBootDisk'], bool):
                    msg = 'isBootDisk must be a bool in disk data: {d}'.format(d=str(disk))
                    raise InvalidOperatingSystemTemplate(msg)
                if disk['isBootDisk']:
                    has_boot_disk = True
                self.disks.append(disk)
        if not has_boot_disk:
            self.disks.append({
                {
                    'capacityInMegabytes': self.root_disk_size,
                    'isAdditionalDisk': False,
                    'isBootDisk': True
                }
            })

    def determine_remote_access_templates(self):
        if OperatingSystemType.needs_remote_access_ssh(self.operating_system_type):
            self.remote_access_templates.append(
                {
                    'name': 'SSH',
                    'type': 'SSH',
                    'port': 22
                }
            )
        if OperatingSystemType.needs_remote_access_vnc(self.operating_system_type):
            self.remote_access_templates.append(
                {
                    'name': 'VNC',
                    'type': 'VNC',
                    'port': 5902,
                    'password': 'milCloud123'
                }
            )
        if OperatingSystemType.needs_remote_access_rdp(self.operating_system_type):
            self.remote_access_templates.append(
                {
                    'name': 'RDP',
                    'type': 'RDP',
                    'port': 3389
                }
            )
