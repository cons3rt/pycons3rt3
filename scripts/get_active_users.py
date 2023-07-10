#!/usr/bin/env python3
"""
Prints a list of active users

"""
import sys
import traceback
from pycons3rt3.exceptions import Cons3rtApiError
from pycons3rt3.cons3rtapi import Cons3rtApi


def main():
    user_list = []

    # Create a Cons3rtApi object
    c = Cons3rtApi()

    # Get the list of site users
    # Query the site for all users
    print('Attempting to query site for all users...')
    try:
        user_list = c.list_active_users()
    except Cons3rtApiError as exc:
        print('There was a problem retrieving the list of users from CONS3RT\n{e}\n{t}'.format(
            e=str(exc), t=traceback.print_exc()
        ))
        return 1

    # Get the active users
    for user in user_list:
        print('Found Active user: {n}'.format(n=user['username']))
    print('Completed, found {n} active users'.format(n=str(len(user_list))))
    return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
