#!/usr/bin/env python


class Scenario(object):

    def __init__(self, name='', config_script=None, teardown_script=None):
        self.name = name
        self.scenario_hosts = []
        self.teardown_script = teardown_script
        self.config_script = config_script

    def add_scenario_host(self, role_name, system_id, subtype='virtualHost', build_order=1, master=False,
                          host_config_script=None, host_teardown_script=None):
        """Add a scenario host to the Scenario object

        :param role_name: (str) role name
        :param system_id: (int) system ID
        :param subtype: (str) see CONS3RT API docs
        :param build_order: (int) see CONS3RT API docs
        :param master: (bool) see CONS3RT API docs
        :param host_config_script: (str) see CONS3RT API docs
        :param host_teardown_script: (str) see CONS3RT API docs
        :return: None
        """
        scenario_host = {'systemRole': role_name, 'systemModule': {}}
        scenario_host['systemModule']['subtype'] = subtype
        scenario_host['systemModule']['id'] = system_id
        scenario_host['systemModule']['buildOrder'] = build_order
        if master:
            scenario_host['systemModule']['master'] = 'true'
        else:
            scenario_host['systemModule']['master'] = 'false'
        if host_config_script:
            scenario_host['systemModule']['configureScenarioConfiguration'] = host_config_script
        if host_teardown_script:
            scenario_host['systemModule']['teardownScenarioConfiguration'] = host_teardown_script
        self.scenario_hosts.append(scenario_host)

    def set_config_script(self, config_script):
        self.config_script = config_script

    def set_teardown_script(self, teardown_script):
        self.teardown_script = teardown_script

    def create(self, cons3rt_api):
        return cons3rt_api.create_scenario(
            name=self.name,
            scenario_hosts=self.scenario_hosts
        )
