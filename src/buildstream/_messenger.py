#
#  Copyright (C) 2019-2020 Bloomberg Finance LP
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library. If not, see <http://www.gnu.org/licenses/>.
#
#  Authors:
#        Angelos Evripiotis <jevripiotis@bloomberg.net>

import os
import datetime
import threading
from contextlib import contextmanager
from typing import Callable, Generator, Optional, TextIO

from . import _signals
from ._exceptions import BstError
from ._message import Message, MessageType, unconditional_messages
from ._state import State, _Task


_RENDER_INTERVAL = datetime.timedelta(seconds=1)


# Time in seconds for which we decide that we want to display subtask information
_DISPLAY_LIMIT = datetime.timedelta(seconds=3)
# If we're in the test suite, we need to ensure that we don't set a limit
if "BST_TEST_SUITE" in os.environ:
    _DISPLAY_LIMIT = datetime.timedelta(seconds=0)


# TimeData class to contain times in an object that can be passed around
# and updated from different places
class _TimeData:
    __slots__ = ["start_time"]

    def __init__(self, start_time: datetime.datetime) -> None:
        self.start_time = start_time


class _JobRecorder:
    def __init__(self, action_name: str, element_key: str, log_filename: str) -> None:
        self.action_name = action_name
        self.element_key = element_key
        self.log_filename = log_filename

        self.log_handle: Optional[TextIO] = None
        self.silence_scope_depth = 0

    @contextmanager
    def enable_recording(self) -> Generator["_JobRecorder", None, None]:
        # Ensure the directory exists first
        directory = os.path.dirname(self.log_filename)
        os.makedirs(directory, exist_ok=True)

        with open(self.log_filename, "a") as logfile:

            # Write one last line to the log and flush it to disk
            def flush_log():

                # If the process currently had something happening in the I/O stack
                # then trying to reenter the I/O stack will fire a runtime error.
                #
                # So just try to flush as well as we can at SIGTERM time
                try:
                    logfile.write("\n\nForcefully terminated\n")
                    logfile.flush()
                except RuntimeError:
                    os.fsync(logfile.fileno())

            self.log_handle = logfile

            with _signals.terminator(flush_log):
                yield self

    # record_message()
    #
    # Records the message if recording is enabled
    #
    # Args:
    #    message (Message): The message to record
    #
    def record_message(self, message: Message) -> None:
        INDENT = "    "
        EMPTYTIME = "--:--:--"
        template = "[{timecode: <8}] {type: <7}"

        # If this message is associated with an element or source plugin, print the
        # full element name of the instance.
        element_name = ""
        if message.element_name:
            template += " {element_name}"
            element_name = message.element_name

        template += ": {message}"

        detail = ""
        if message.detail is not None:
            template += "\n\n{detail}"
            detail = message.detail.rstrip("\n")
            detail = INDENT + INDENT.join(detail.splitlines(True))

        timecode = EMPTYTIME
        if message.message_type in (MessageType.SUCCESS, MessageType.FAIL):
            hours, remainder = divmod(int(message.elapsed.total_seconds()), 60 ** 2)
            minutes, seconds = divmod(remainder, 60)
            timecode = "{0:02d}:{1:02d}:{2:02d}".format(hours, minutes, seconds)

        text = template.format(
            timecode=timecode,
            element_name=element_name,
            type=message.message_type.upper(),
            message=message.message,
            detail=detail,
        )

        # Write to the open log file
        assert self.log_handle is not None
        self.log_handle.write("{}\n".format(text))
        self.log_handle.flush()


class Messenger:
    def __init__(self) -> None:
        self._state: Optional[State] = None
        self._next_render: Optional[datetime.datetime] = None  # A Time object
        self._active_simple_tasks: int = 0
        self._render_status_cb: Optional[Callable[[], None]] = None

        self._message_handler: Optional[Callable[[Message], None]] = None
        self._global_silence_scope_depth = 0

        self._locals = threading.local()
        self._locals.job = None

    # set_message_handler()
    #
    # Sets the handler for any status messages propagated through
    # the context.
    #
    # Args:
    #   handler: The handler to call on message
    #
    def set_message_handler(self, handler: Callable[[Message], None]) -> None:
        self._message_handler = handler

    # set_state()
    #
    # Sets the State object within the Messenger
    #
    # Args:
    #    state: The state to set
    #
    def set_state(self, state: State) -> None:
        self._state = state

    # set_render_status_cb()
    #
    # Sets the callback to use to render status
    #
    # Args:
    #    callback: The Callback to be notified
    #
    def set_render_status_cb(self, callback: Callable[[], None]) -> None:
        self._render_status_cb = callback

    # _silent_messages():
    #
    # Returns: Whether messages are currently being silenced
    #
    def _silent_messages(self) -> bool:
        if self._locals.job is not None:
            return self._locals.job.silence_scope_depth > 0
        return self._global_silence_scope_depth > 0

    # message():
    #
    # Proxies a message back to the caller, this is the central
    # point through which all messages pass.
    #
    # Args:
    #    message: A Message object
    #
    def message(self, message: Message) -> None:
        job = self._locals.job

        if job is not None:
            message.action_name = job.action_name
            message.logfile = job.log_filename

            # If no key has been set at this point, and the element job has
            # a related key, set it.
            if message.element_key is None:
                message.element_key = job.element_key

            # Job always record messages
            self._locals.job.record_message(message)

            # Don't log LOG messages from jobs
            if message.message_type == MessageType.LOG:
                return

        # Don't forward if it is currently silent
        if self._silent_messages() and (message.message_type not in unconditional_messages):
            return

        assert self._message_handler is not None
        self._message_handler(message)

    # silence()
    #
    # A context manager to silence messages, this behaves in
    # the same way as the `silent_nested` argument of the
    # timed_activity() context manager: all but
    # _message.unconditional_messages will be silenced.
    #
    # Args:
    #    actually_silence: Whether to actually do the silencing, if False then
    #                      this context manager does not affect anything.
    #
    @contextmanager
    def silence(self, *, actually_silence: bool = True) -> Generator[None, None, None]:
        if not actually_silence:
            yield
            return

        in_job = self._locals.job is not None

        if in_job:
            self._locals.job.silence_scope_depth += 1
        else:
            self._global_silence_scope_depth += 1

        try:
            yield
        finally:
            if in_job:
                assert self._locals.job.silence_scope_depth > 0
                self._locals.job.silence_scope_depth -= 1
            else:
                assert self._global_silence_scope_depth > 0
                self._global_silence_scope_depth -= 1

    # timed_activity()
    #
    # Context manager for performing timed activities and logging those
    #
    # Args:
    #    activity_name: The name of the activity
    #    element_name: Optionally, the element full name of the plugin related to the message
    #    detail: An optional detailed message, can be multiline output
    #    silent_nested: If True, all but _message.unconditional_messages are silenced
    #
    @contextmanager
    def timed_activity(
        self,
        activity_name: str,
        *,
        element_name: Optional[str] = None,
        detail: Optional[str] = None,
        silent_nested: bool = False
    ) -> Generator[None, None, None]:
        with self.timed_suspendable() as timedata:
            try:
                # Push activity depth for status messages
                message = Message(MessageType.START, activity_name, detail=detail, element_name=element_name)
                self.message(message)
                with self.silence(actually_silence=silent_nested):
                    yield

            except BstError:
                # Note the failure in status messages and reraise, the scheduler
                # expects an error when there is an error.
                elapsed = datetime.datetime.now() - timedata.start_time
                message = Message(MessageType.FAIL, activity_name, elapsed=elapsed, element_name=element_name)
                self.message(message)
                raise

            elapsed = datetime.datetime.now() - timedata.start_time
            message = Message(MessageType.SUCCESS, activity_name, elapsed=elapsed, element_name=element_name)
            self.message(message)

    # simple_task()
    #
    # Context manager for creating a task to report progress to.
    #
    # Args:
    #    activity_name: The name of the activity
    #    element_name: Optionally, the element full name of the plugin related to the message
    #    full_name: Optionally, the distinguishing name of the activity, e.g. element name
    #    silent_nested: If True, all but _message.unconditional_messages are silenced
    #
    # Yields: A Task object that represents this activity, principally used to report progress
    #
    @contextmanager
    def simple_task(
        self,
        activity_name: str,
        *,
        element_name: Optional[str] = None,
        full_name: Optional[str] = None,
        silent_nested: bool = False
    ) -> Generator[Optional[_Task], None, None]:
        # Bypass use of State when none exists (e.g. tests)
        if not self._state:
            with self.timed_activity(activity_name, element_name=element_name, silent_nested=silent_nested):
                yield None
            return

        if not full_name:
            full_name = activity_name

        with self.timed_suspendable() as timedata:
            try:
                message = Message(MessageType.START, activity_name, element_name=element_name)
                self.message(message)

                task = self._state.add_task(activity_name, full_name)
                task.set_render_cb(self._render_status)
                self._active_simple_tasks += 1
                if not self._next_render:
                    self._next_render = datetime.datetime.now() + _RENDER_INTERVAL

                with self.silence(actually_silence=silent_nested):
                    yield task

            except BstError:
                elapsed = datetime.datetime.now() - timedata.start_time
                message = Message(MessageType.FAIL, activity_name, elapsed=elapsed, element_name=element_name)
                self.message(message)
                raise
            finally:
                self._state.remove_task(activity_name, full_name)
                self._active_simple_tasks -= 1
                if self._active_simple_tasks == 0:
                    self._next_render = None

            elapsed = datetime.datetime.now() - timedata.start_time
            detail = None

            if task.current_progress is not None and elapsed > _DISPLAY_LIMIT:
                if task.maximum_progress is not None:
                    detail = "{} of {} subtasks processed".format(task.current_progress, task.maximum_progress)
                else:
                    detail = "{} subtasks processed".format(task.current_progress)
            message = Message(
                MessageType.SUCCESS, activity_name, elapsed=elapsed, detail=detail, element_name=element_name
            )
            self.message(message)

    # record_job()
    #
    # Records all messages in a log file while the context manager
    # is active.
    #
    # In addition to automatically writing all messages to the
    # specified logging file, an open file handle for process stdout
    # and stderr will be available via the Messenger.get_log_handle() API,
    # and the full logfile path will be available via the
    # Messenger.get_log_filename() API.
    #
    # Args:
    #     filename: A logging directory relative filename, the pid and .log
    #               extension will be automatically appended
    #
    #     logdir : The path to the log file directory.
    #
    # Yields: The fully qualified log filename
    #
    @contextmanager
    def record_job(
        self, action_name: str, element_key: str, filename: str, logdir: str
    ) -> Generator[_JobRecorder, None, None]:
        # We dont allow recursing in this context manager, and
        # we also do not allow it in the main process.
        assert not hasattr(self._locals, "job") or self._locals.job is None

        log_filename = os.path.join(logdir, "{}.{}.log".format(filename, os.getpid()))
        self._locals.job = _JobRecorder(action_name, element_key, log_filename)

        with self._locals.job.enable_recording() as job:
            yield job

        self._locals.job = None

    # get_log_handle()
    #
    # Fetches the active log handle, this will return the active
    # log file handle when the Messenger.recorded_messages() context
    # manager is active
    #
    # Returns: The active logging file handle, or None
    #
    def get_log_handle(self) -> Optional[str]:
        if self._locals.job is not None:
            return self._locals.job.log_handle
        return None

    # get_log_filename()
    #
    # Fetches the active log filename, this will return the active
    # log filename when the Messenger.recorded_messages() context
    # manager is active
    #
    # Returns: The active logging filename, or None
    #
    def get_log_filename(self) -> str:
        return self._locals.job.log_filename

    # timed_suspendable()
    #
    # A contextmanager that allows an activity to be suspended and can
    # adjust for clock drift caused by suspending
    #
    # Yields:
    #    An object that contains the time the activity started
    #
    @contextmanager
    def timed_suspendable(self) -> Generator[_TimeData, None, None]:
        # Note: timedata needs to be in a namedtuple so that values can be
        # yielded that will change
        timedata = _TimeData(start_time=datetime.datetime.now())
        stopped_time = None

        def stop_time():
            nonlocal stopped_time
            stopped_time = datetime.datetime.now()

        def resume_time():
            nonlocal timedata
            nonlocal stopped_time
            sleep_time = datetime.datetime.now() - stopped_time
            timedata.start_time += sleep_time

        with _signals.suspendable(stop_time, resume_time):
            yield timedata

    # _render_status()
    #
    # Calls the render status callback set in the messenger, but only if a
    # second has passed since it last rendered.
    #
    def _render_status(self) -> None:
        assert self._next_render

        # self._render_status_cb()
        now = datetime.datetime.now()
        if self._render_status_cb and now >= self._next_render:
            self._render_status_cb()
            self._next_render = now + _RENDER_INTERVAL
