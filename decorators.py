"""
Utility functions

@author: Eemil Nyyssönen
"""
import functools
import time
import logging

logger = logging.getLogger(__name__)

def timer(func):
    """Decorator to get the runtime of a function"""
    @functools.wraps(func)
    def wrapper_timer(*args, **kwargs):
        start_time = time.perf_counter()      # 1
        value      = func(*args, **kwargs)
        end_time   = time.perf_counter()      # 2
        run_time   = end_time - start_time    # 3
        logger.info(f"Finished {func.__name__!r} in {run_time:.4f} secs")
        return value
    return wrapper_timer
