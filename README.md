# renicer

This works together with [Splosh](https://github.com/plaguedbypenguins/splosh/) to automatically renice long running processes and threads on cluster login nodes.

Run like
```
renicer.py < /dev/null &
```

It requires python3, cgroups v1, and a cgroup hierachy setup by Splosh. eg. "/sys/fs/cgroup/cpuset/aardvark/<users>/"

There are some crappy systemd wrappers in the systemd/ directory, but I'm sure you can do better...

Known issues:
* splosh only sets up the cgroup structure after the first login, so starting renicer.py as a daemon at boot will fail. Perhaps there's a way for systemd to wait for this dir to be created before starting the daemon? Patches welcome.
* i/o intensive tasks like rsync and scp/sftp will also eventually accrete enough cpu time to be reniced. I don't care about this, but you might.

Robin Humble.  insert this github username @ gmail.com
