#!/usr/bin/env python3

from pycons3rt3.cons3rtapi import Cons3rtApi

c = Cons3rtApi(config_file='/path/to/config.json')

c.set_project_token('Project Name')

identity = c.create_host_identity(
    dr_id=12345,
    host_id=6789,
    service_type='BUCKET',
    service_identifier='testbucket-12345678910'
)

print(identity)
