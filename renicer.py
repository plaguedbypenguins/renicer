#!/usr/bin/env python3

# rjh; Fri Nov 26 16:38:51 AEDT 2021
# tiny daemon to renice long running login node tasks

# NOTE: this works together with 'splosh' to only target user processes in the cgroup hierarchy setup by splosh.
#    it expects a hierarchy like /sys/fs/cgroup/cpuset/aardvark/<users>/

# for info on the format of /proc/<pid>/stat see the kernel git doco file
#   Documentation/filesystems/proc.rst

import os, time
import logging, logging.handlers

base='/sys/fs/cgroup/cpuset/aardvark'

# list nice vs. time (in seconds) thresholds in order of most niced (longest running), to least niced (shortest running).
#   eg. an entry to renice to 10 after 180mins would be represented as
#        (10, 180*60)
#
# these must be in order of longest time to shortest time:
thresholds = [ (15, 720*60), (10, 180*60), (4, 60*60) ]

# debug:
#thresholds = [ (15, 720), (10, 180), (4, 60) ]

niceMax=thresholds[0][0]
minCputime=thresholds[-1][1]

def getLog(loglevel):
   log = logging.getLogger('renicer')
   loghdlr = logging.handlers.SysLogHandler('/dev/log')
   #logfmt = logging.Formatter("renicer: %(levelname)-10s %(message)s", "%x %X")
   logfmt = logging.Formatter("renicer: %(message)s", "%X")
   loghdlr.setFormatter(logfmt)
   log.addHandler(loghdlr)
   log.setLevel(loglevel.upper())
   return log

# debug > info > warning > error > critical
log = getLog('debug')

# this class wraps /proc/<pid>/stat and carries state for a given (pid, user)
class taskstat:
   def __init__(self, pid, user):
      self.pid = pid
      self.user = user

   def readStat(self):
      try:
         self.t = time.time()
         # handle newline characters etc. in process names. java. sigh
         s = ''
         with open('/proc/' + self.pid + '/stat', 'r') as f:
            for l in f.readlines():
               s += l.strip()
         self.s = s.split()
         return True
      except:
         pass
      return False

   def isLongTask(self):
      if not self.readStat():  # err, so skip. maybe task is no longer there
         return False

      self.tcomm = self.s[1]
      if self.tcomm == '(sshd)':  # skip user sshd's
         return False

      self.nice=int(self.s[18])
      if self.nice >= niceMax:   # already max nice
         return False

      self.cpuTime()
      if self.cputime < minCputime:
         return False

      return True

   def cpuTime(self):
      utime=int(self.s[13])  # utime         user mode jiffies
      stime=int(self.s[14])  # stime         kernel mode jiffies
      self.cputime = (utime + stime)/100   # convert to seconds

   def cpuTimeUsed(self):
      t0 = self.t
      cputime0 = self.cputime

      if not self.readStat():  # err, so skip. maybe task is no longer there
         return False
      self.cpuTime()

      self.cpuused=(self.cputime-cputime0)/(self.t-t0)
      self.state=self.s[2]
      self.nice=int(self.s[18])
      return True

   def running(self):
      # check for Running state, or using >90% of a core
      if self.state == 'R' or self.cpuused > 0.9:
         return True
      return False

   def intermittent(self):
      start_time_seconds=int(self.s[21])/100  # start_time    time the process started after system boot
      with open('/proc/uptime', 'r') as f:
        uptime_seconds = float(f.readline().split()[0])
      runtime = uptime_seconds - start_time_seconds

      self.intermittent = self.cputime/runtime

      # if average cpu used is low then it's intermittent
      log.debug('intermittent %.2f' % self.intermittent + ' user ' + self.user + ' s ' + str(self.s))
      if self.intermittent < 0.25:
         return True
      return False

   def renice(self, n):
      if self.nice >= n:  # process is already too nice
         return
      log.info('user ' + self.user + ' cputime %.1f' % self.cputime + ' cpuused %.2f' % self.cpuused + ' intermittent %.2f' % self.intermittent + ' renice to %d' % n + '. ' + str(self.s))
      os.setpriority(os.PRIO_PROCESS, int(self.pid), n)

while True:
   tasks=[]
   cnt = 0
   with os.scandir(base) as it:
      for entry in it:
         if not entry.name.startswith('.') and entry.is_dir():
            with open(base + '/' + entry.name + '/tasks', 'r') as f:
               for l in f.readlines():
                  task = taskstat(l.strip(), entry.name)
                  cnt += 1
                  if task.isLongTask():
                     tasks.append(task)
   log.debug('tasks %d' % cnt + ' long tasks %d' % len(tasks))

   # wait for a second and check all task cputimes again to see if they're running or idle
   time.sleep(1)

   for t in tasks:
      # compute cpu time used in the last second
      if not t.cpuTimeUsed():  # err, so skip. maybe task is no longer there
         continue

      # only look at R state tasks, or those actively using most of at least 1 core
      if not t.running():
         continue

      # be lenient on things like Xvnc, jupyter, matlab, ...
      # they may have been left open for days and accumulated lots of cpu, and
      # may right now be in R state, but are only active at a low level.
      # ie. they're idle most of the time
      if t.intermittent():
         continue

      # decide on the renice level, depending on the hours of cpu it's used...
      for n, tm in thresholds:
         if t.cputime > tm:
            t.renice(n)
            break

   time.sleep(300)
