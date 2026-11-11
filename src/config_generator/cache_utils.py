import contextlib
import os


def cached_file_valid(path, project_mtime):
    """ Return whether the cached file was generated from the project version with the specified modification time.

    If the modification time of the project is unknown, any existing cached file is valid.
    """
    if not os.path.exists(path):
        return False
    # The file system of the cached file may only store whole seconds
    return project_mtime is None or os.stat(path).st_mtime_ns in (project_mtime, project_mtime // 10**9 * 10**9)

def stamp_cached_file(path, project_mtime):
    """ Set the modification time of the cached file to the modification time of the project it was generated from. """
    if project_mtime is not None:
        # A file owned by another user cannot be stamped: it is read again on the next cached run
        with contextlib.suppress(OSError):
            os.utime(path, ns=(project_mtime, project_mtime))
