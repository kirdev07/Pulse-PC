"""Bounded daemon workers for OS I/O which Windows cannot always interrupt.

Cancelling an await cannot stop an in-progress filesystem syscall. These workers
finish it when Windows returns, but never hold application shutdown hostage.
"""
from concurrent.futures import Future, ThreadPoolExecutor
import queue
import threading
import time


class FileIOExecutor(ThreadPoolExecutor):
    def __init__(self, max_workers=4):
        super().__init__(max_workers=max_workers)
        self.io_queue = queue.Queue()
        self.io_lock = threading.Lock()
        self.io_closed = False
        self.io_threads = []
        self.io_limit = max_workers

    @staticmethod
    def work(tasks):
        while True:
            item = tasks.get()
            if item is None:
                return
            future, function, args, kwargs = item
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(function(*args, **kwargs))
                except BaseException as exc:
                    future.set_exception(exc)
            del item, future, function, args, kwargs

    def submit(self, fn, /, *args, **kwargs):
        with self.io_lock:
            if self.io_closed:
                raise RuntimeError("File I/O executor is closed")
            if not self.io_threads:
                for index in range(self.io_limit):
                    thread = threading.Thread(target=self.work, args=(self.io_queue,),
                                              name=f"PulsePC-io-{index}", daemon=True)
                    thread.start()
                    self.io_threads.append(thread)
            future = Future()
            self.io_queue.put((future, fn, args, kwargs))
            return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self.io_lock:
            if not self.io_closed:
                self.io_closed = True
                # Queued work must not begin after the owner has stopped.
                while True:
                    try:
                        self.io_queue.get_nowait()[0].cancel()
                    except queue.Empty:
                        break
                for _ in self.io_threads:
                    self.io_queue.put(None)
        if wait:
            deadline = time.monotonic() + 1
            for thread in self.io_threads:
                if thread is not threading.current_thread():
                    thread.join(max(0, deadline - time.monotonic()))
