#!/usr/bin/env python3

import traceback

# Setup:
class DatabaseError(Exception):
    pass

# Setup:
class TestError(Exception):
    pass

# Python 3 only
class FileDatabase:
    def __init__(self, filename):
        try:
            self.file = open(filename)
        except IOError as exc:
            raise DatabaseError('failed to open database file') from exc

class TestExc(object):
    def __init__(self):
        pass

    def test(self):
        try:
            fd = FileDatabase('non_existent_file.txt')
        except Exception as exc:
            raise TestError('Test error found') from exc



def main():
    # Testing the above:
    #try:
    #    fd = FileDatabase('non_existent_file.txt')
    #except Exception as e:
    #    print('Problem: {t}'.format(t=traceback.format_exc()))


    t = TestExc()

    try:
        t.test()
    except Exception:
        print('Problem: {t}'.format(t=traceback.format_exc()))



if __name__ == '__main__':
    main()

