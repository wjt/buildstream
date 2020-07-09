from cpython.pystate cimport PyThreadState_SetAsyncExc
from cpython.ref cimport PyObject


def abort_thread(long id):
    res = PyThreadState_SetAsyncExc(id, <PyObject*> BaseException)
    assert res == 1
