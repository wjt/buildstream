from cpython.pystate cimport PyThreadState_SetAsyncExc
from cpython.ref cimport PyObject
from ..._signals import TerminateException


def abort_thread(long thread_id):
    res = PyThreadState_SetAsyncExc(thread_id, <PyObject*> TerminateException)
    assert res == 1
