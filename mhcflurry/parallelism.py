import traceback
import sys
import os
from multiprocessing import Pool, Queue, cpu_count
from six.moves import queue
from multiprocessing.util import Finalize
from pprint import pprint
import random

import numpy

from .common import set_keras_backend


def add_worker_pool_args(parser):
    group = parser.add_argument_group("Worker pool")

    group.add_argument(
        "--num-jobs",
        default=1,
        type=int,
        metavar="N",
        help="Number of processes to parallelize training over. Experimental. "
             "Set to 0 for serial run. Default: %(default)s.")
    group.add_argument(
        "--backend",
        choices=("tensorflow-gpu", "tensorflow-cpu", "tensorflow-default"),
        help="Keras backend. If not specified will use system default.")
    group.add_argument(
        "--gpus",
        type=int,
        metavar="N",
        help="Number of GPUs to attempt to parallelize across. Requires running "
             "in parallel.")
    group.add_argument(
        "--max-workers-per-gpu",
        type=int,
        metavar="N",
        default=1000,
        help="Maximum number of workers to assign to a GPU. Additional tasks will "
             "run on CPU.")
    group.add_argument(
        "--max-tasks-per-worker",
        type=int,
        metavar="N",
        default=None,
        help="Restart workers after N tasks. Workaround for tensorflow memory "
             "leaks. Requires Python >=3.2.")


def worker_pool_with_gpu_assignments_from_args(args):
    return worker_pool_with_gpu_assignments(
        num_jobs=args.num_jobs,
        num_gpus=args.gpus,
        backend=args.backend,
        max_workers_per_gpu=args.max_workers_per_gpu,
        max_tasks_per_worker=args.max_tasks_per_worker
    )


def worker_pool_with_gpu_assignments(
        num_jobs,
        num_gpus=0,
        backend=None,
        max_workers_per_gpu=1,
        max_tasks_per_worker=None):

    num_workers = num_jobs if num_jobs else cpu_count()

    if num_workers == 0:
        if backend:
            set_keras_backend(backend)
        return None

    worker_init_kwargs = None
    if num_gpus:
        print("Attempting to round-robin assign each worker a GPU.")
        if backend != "tensorflow-default":
            print("Forcing keras backend to be tensorflow-default")
            backend = "tensorflow-default"

        gpu_assignments_remaining = dict((
            (gpu, max_workers_per_gpu) for gpu in range(num_gpus)
        ))
        worker_init_kwargs = []
        for worker_num in range(num_workers):
            if gpu_assignments_remaining:
                # Use a GPU
                gpu_num = sorted(
                    gpu_assignments_remaining,
                    key=lambda key: gpu_assignments_remaining[key])[0]
                gpu_assignments_remaining[gpu_num] -= 1
                if not gpu_assignments_remaining[gpu_num]:
                    del gpu_assignments_remaining[gpu_num]
                gpu_assignment = [gpu_num]
            else:
                # Use CPU
                gpu_assignment = []

            worker_init_kwargs.append({
                'gpu_device_nums': gpu_assignment,
                'keras_backend': backend
            })
            print("Worker %d assigned GPUs: %s" % (
                worker_num, gpu_assignment))

    worker_pool = make_worker_pool(
        processes=num_workers,
        initializer=worker_init,
        initializer_kwargs_per_process=worker_init_kwargs,
        max_tasks_per_worker=max_tasks_per_worker)
    return worker_pool


def make_worker_pool(
        processes=None,
        initializer=None,
        initializer_kwargs_per_process=None,
        max_tasks_per_worker=None):
    """
    Convenience wrapper to create a multiprocessing.Pool.

    This function adds support for per-worker initializer arguments, which are
    not natively supported by the multiprocessing module. The motivation for
    this feature is to support allocating each worker to a (different) GPU.

    IMPLEMENTATION NOTE:
        The per-worker initializer arguments are implemented using a Queue. Each
        worker reads its arguments from this queue when it starts. When it
        terminates, it adds its initializer arguments back to the queue, so a
        future process can initialize itself using these arguments.

        There is one issue with this approach, however. If a worker crashes, it
        never repopulates the queue of initializer arguments. This will prevent
        any future worker from re-using those arguments. To deal with this
        issue we add a second 'backup queue'. This queue always contains the
        full set of initializer arguments: whenever a worker reads from it, it
        always pushes the pop'd args back to the end of the queue immediately.
        If the primary arg queue is ever empty, then workers will read
        from this backup queue.

    Parameters
    ----------
    processes : int
        Number of workers. Default: num CPUs.

    initializer : function, optional
        Init function to call in each worker

    initializer_kwargs_per_process : list of dict, optional
        Arguments to pass to initializer function for each worker. Length of
        list must equal the number of workers.

    max_tasks_per_worker : int, optional
        Restart workers after this many tasks. Requires Python >=3.2.

    Returns
    -------
    multiprocessing.Pool
    """

    if not processes:
        processes = cpu_count()

    pool_kwargs = {
        'processes': processes,
    }
    if max_tasks_per_worker:
        pool_kwargs["maxtasksperchild"] = max_tasks_per_worker

    if initializer:
        if initializer_kwargs_per_process:
            assert len(initializer_kwargs_per_process) == processes
            kwargs_queue = Queue()
            kwargs_queue_backup = Queue()
            for kwargs in initializer_kwargs_per_process:
                kwargs_queue.put(kwargs)
                kwargs_queue_backup.put(kwargs)
            pool_kwargs["initializer"] = worker_init_entry_point
            pool_kwargs["initargs"] = (
                initializer, kwargs_queue, kwargs_queue_backup)
        else:
            pool_kwargs["initializer"] = initializer

    worker_pool = Pool(**pool_kwargs)
    print("Started pool: %s" % str(worker_pool))
    pprint(pool_kwargs)
    return worker_pool


def worker_init_entry_point(
        init_function, arg_queue=None, backup_arg_queue=None):
    kwargs = {}
    if arg_queue:
        try:
            kwargs = arg_queue.get(block=False)
        except queue.Empty:
            print("Argument queue empty. Using round robin arg queue.")
            kwargs = backup_arg_queue.get(block=True)
            backup_arg_queue.put(kwargs)

        # On exit we add the init args back to the queue so restarted workers
        # (e.g. when when running with maxtasksperchild) will pickup init
        # arguments from a previously exited worker.
        Finalize(None, arg_queue.put, (kwargs,), exitpriority=1)

    print("Initializing worker: %s" % str(kwargs))
    init_function(**kwargs)


def worker_init(keras_backend=None, gpu_device_nums=None):
    # Each worker needs distinct random numbers
    numpy.random.seed()
    random.seed()
    if keras_backend or gpu_device_nums:
        print("WORKER pid=%d assigned GPU devices: %s" % (
            os.getpid(), gpu_device_nums))
        set_keras_backend(
            keras_backend, gpu_device_nums=gpu_device_nums)


# Solution suggested in https://bugs.python.org/issue13831
class WrapException(Exception):
    """
    Add traceback info to exception so exceptions raised in worker processes
    can still show traceback info when re-raised in the parent.
    """
    def __init__(self):
        exc_type, exc_value, exc_tb = sys.exc_info()
        self.exception = exc_value
        self.formatted = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    def __str__(self):
        return '%s\nOriginal traceback:\n%s' % (Exception.__str__(self), self.formatted)


def call_wrapped(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except:
        raise WrapException()


def call_wrapped_kwargs(function, kwargs):
    return call_wrapped(function, **kwargs)