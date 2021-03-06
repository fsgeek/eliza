import gzip
import time
import os
import sys
import subprocess
import errno
import csv
import argparse
import traceback
import gc
import bisect
# import numpypy as np
import ConfigParser
# import intervaltree as it
# import matplotlib.pyplot as plt
# from pylab import *
from collections import deque
from os import listdir
from os.path import isfile, join
from multiprocessing import Pool, TimeoutError, Process, Queue, Lock
from ep_stats import ep_stats

debugl = ['1','2','3','4']

parser = argparse.ArgumentParser(prog="eliza", description="A tool to analyze epochs")
parser.add_argument('-d', dest='debug', default ='0', help="Debug levels", choices=debugl)
parser.add_argument('-t', dest='time_intv', default = 5, help="Time interval to inspect")
parser.add_argument('-r', dest='logdir', help="Log directory containing per-thread epoch logs")
parser.add_argument('-v', '--version', action='version', version='%(prog)s v0.1', help="Display version and quit")

try:
	args = parser.parse_args()
except:
	sys.exit(0)

wpid = -1 # Worker pid
est = None
debug = 0
lookback_time = 0.000001 # 1 us
lookback_time = 0.000005 # 5 us
lookback_time = 0.00001  # 10 us
lookback_time = 0.000015 # 15 us
lookback_time = 0.00002  # 20 us
lookback_time = 0.000025 # 25 us
lookback_time = 0.00003  # 30 us
lookback_time = 0.000035 # 35 us
lookback_time = 0.000040 # 40 us
lookback_time = 0.000045 # 45 us
lookback_time = 0.00005  # 50 us
loskback_time = 0.000010 # 5 us
lookback_time = 0.00005  # 50 us
lookback_time = 0.0005   # 500 us
lookback_time = 0.005    # 5000 us
lookback_time = 0.01     # 10000 us
lookback_time = 0.02     # 20000 us
lookback_time = 0.05     # 50000 us
lookback_time = 0.5      # 500000 us
lookback_time = int(args.time_intv) # or you could do times 1,000,000
debug = int(args.debug)
print "*************************************"
print "Calculating thread dependencies"
print "Look back time = ", lookback_time, " microsec"
print "Debug level    = ", debug
print "*************************************"
# Keep the two separate so that you can collectively read in lines later
# if the files are too big
f_to_epochs_stime_m = {}
f_to_epochs_etime_m = {}
f_to_lnnums_m = {}
f_to_fp = {}


import inspect

def print_frame():

  callerframerecord = inspect.stack()[1]    # 0 represents this line
                                            # 1 represents line at caller
  frame = callerframerecord[0]
  info = inspect.getframeinfo(frame)
  print info.function, info.lineno          
  
 
'''
	Start with an empty
	Keep filling it so long as the indices returned by bisect engulf the 
	entire list
	When the left most index is no longer 0, remove as many elements
	as the index returned by bisect
'''
def make_index_by_etime(logdir, f):
	global f_to_epochs_etime_m
	f2e = []
	with open(logdir + '/' + f, 'r') as fp:
		for lno,l in enumerate(fp):
			try:
				# this may fail due to out-range index, hence "try"
				epstr = l.split(';')[3]
				stime = est.get_stime_from_str(epstr)
				etime = est.get_etime_from_str(epstr)
				f2e.append((etime, lno+1))
			except:
				continue
	fp.close()
	f_to_epochs_etime_m[f] = f2e
	
def make_index_by_stime(logdir, f):
	global f_to_epochs_stime_m
	f2e = []
	with open(logdir + '/' + f, 'r') as fp:
		for lno,l in enumerate(fp):
			try:
				# this may fail due to out-range index, hence "try"
				epstr = l.split(';')[3]
				stime = est.get_stime_from_str(epstr)
				etime = est.get_etime_from_str(epstr)
				f2e.append((stime, lno+1))
			except:
				continue
	fp.close()
	f_to_epochs_stime_m[f] = f2e
	''' 
		We could have one giant index for all epochs in the env
		indexed using their start times. But then concurrent epochs
		from two different guest threads with the same start time will 
		contend for a space in the index and I am not sure how python
		handles such contention - chaining, or what ? I am assuming only
		one of the contending epochs gets to reside in the index and this can
		make me miss some dependencies. It doesn't matter if there are plenty
		of dependencies already and missing one or two doesn't matter. But at 
		this point we don't know so to be safe we will not have one index
		for all epochs in the env but one index per guest thread.
	'''
def make_lnmap(logdir, f):
	global f_to_lnnums_m
	lno_to_lines_m = {}
	with open(logdir + '/' + f, 'r') as fp:
		for lno,l in enumerate(fp): # 0 to n - 1
			try:
				tmpl = []
				l_addr = l.split(';')[1].split(',')
				tmpl.append(l_addr)

				epstr = l.split(';')[3]
				stime = est.get_stime_from_str(epstr)
				etime = est.get_etime_from_str(epstr)
				tmpl.append((stime,etime))		

				writers = l.split(';')[2].split(',')
				tmpl.append(writers)
				
				assert len(l_addr) == len(writers)
				# There can only be as many writers as there are addresses
				# since for each address we record the last writer !
				lno_to_lines_m[lno+1] = tmpl
			except:
				continue
	fp.close()
	'''
		The structure here is ass follows :
		f -> lno_to_lines_map -> line num -> [[list of NVM addrs] <0>, 
											(tuple of time stamps)<1>, 
											[list of writers]<2>]
	'''
	f_to_lnnums_m[f] = lno_to_lines_m
	
def find_recent_past_ep_stime_helper(f, time_, time):
	''' Return all epochs that STARTED between stime_ and stime'''
	f2e   = f_to_epochs_stime_m[f]
	pos_  = bisect.bisect_left(f2e, (time_,))
	pos   = bisect.bisect_left(f2e, (time,))

	if pos > pos_:
		st1,sno = f2e[pos_]
		st2,eno = f2e[pos-1] # To avoid index-out-of-range error
		assert time_ <= st1 and st1 <= time
		assert time_ <= st2 and st2 <= time
		assert sno <= eno
		return (sno,eno,st1,st2)
		# iterate from eno to sno
	return None

def find_recent_past_ep_etime_helper(f, time_, time):
	''' Return all epochs that ENDED between time_ and time'''

	'''
		read the file to populate a sequence of epochs that falls between
		time_ and time.
			- Eliminate epochs from the start of the sequence that do
			  not fall in the time interval. Update the HT.
			- Append epochs that fall in the time interval. Update the HT.
		If EOF, return None.
	'''
	dl = 2
	global debug
	global f_to_fp
	global f_to_epochs_etime_m # IDs epoch by end_time and line_num
	global f_to_lnnums_m # Contains more details about an epoch
	
	if debug > dl:
		print_frame()
	

	if f not in f_to_fp:
		f_to_fp[f] = (open(logdir + '/' + f, 'r'), -1)
	fp = f_to_fp[f][0]
	lnnum = f_to_fp[f][1] 


	if debug > dl:
		print_frame()
	
	if f not in f_to_epochs_etime_m:
		f_to_epochs_etime_m[f] = deque([])
	f2e = f_to_epochs_etime_m[f]
	
	if debug > dl:
		print_frame()

	if f not in f_to_lnnums_m:
		f_to_lnnums_m[f] = {}
	lno2lines_m = f_to_lnnums_m[f]

	if debug > dl:
		print_frame()

	''' Evict epochs that do not fall in the desired interval '''
	# for intra thread only for now but works for inter thread as well
	evict = []
	for (et,lno) in f2e:
		if time_ <= et and et < time:
			# You stop at the first epoch that falls in the interval
			if debug > dl:
				print_frame()
			break
		else:
			evict.append(lno)
			continue

	for lno in evict:
		if debug > dl:
			print_frame()
			print "evicting", lno, lno2lines_m[lno]
		lno2lines_m.pop(lno)
		xxx,__lno = f2e.popleft()
		assert __lno == lno

	if debug > dl:
		print_frame()

	''' 
		Append a few more epochs that fall in the desired interval
		The trailing epochs may not fall in the desired interval. 
	'''
	for l in fp: # 0 to n - 1
		try:
			lnnum += 1
			# this may fail due to out-range index, hence "try"
			if debug > dl:
				print_frame()

			tmpl = []
			l_addr = l.split(';')[1].split(',')
			tmpl.append(l_addr)

			epstr = l.split(';')[3]
			stime = est.get_stime_from_str(epstr)
			etime = est.get_etime_from_str(epstr)
			tmpl.append((stime,etime))		
			
			writers = l.split(';')[2].split(',')
			tmpl.append(writers)
				
			assert len(l_addr) == len(writers)
			# There can only be as many writers as there are addresses
			# since for each address we record the last writer !

			if debug > dl:
				print "caching", lnnum+1, tmpl
				print_frame()

			f2e.append((etime, lnnum+1))
			lno2lines_m[lnnum+1] = tmpl

			if (etime >= time):
				if debug > dl:
					print_frame()
				break			

		except:
			continue
	
	f_to_fp[f] = (fp, lnnum)
	f_to_epochs_etime_m[f] = f2e
	f_to_lnnums_m[f] = lno2lines_m

	if len(f2e) > 0:
		et1,sno = f2e[0]
		et2,eno = et1,sno
		if time_ <= et1 and et1 < time:
			for (et,lno) in f2e:
				if et < time:
					et2,eno = et,lno
				else:
					return (sno, eno, et1, et2)
		else:
			return None
	else:
		return None		
		
	'''
	if (len(f2e)-1) > 0:
		et1,sno = f2e[0]
		et2,eno = f2e[len(f2e)-2] # To avoid index-out-of-range error

		assert (time_ <= et1 and et1 < time)
		assert sno <= eno
		if debug > dl:
			print_frame()

		return (sno,eno,et1,et2)
	else:
		if debug > dl:
			print_frame()

		return None
	'''

def find_recent_past_ep(f, time_, time):
	''' Return all epochs that STARTED between time_ and time
	t = find_recent_past_ep_stime_helper(f, time_, time)
	if t is not None:
		sno_st, eno_st, st1, st2 = t
	else:
		return t
	'''
		
	''' Return all epochs that ENDED between time_ and time'''
	t = find_recent_past_ep_etime_helper(f, time_, time)
	if t is not None:
		sno_et, eno_et, et1, et2 = t
	else:
		return t

	'''
		Note : As a result of this really excellent coding (no sarcasm),
		some epochs are being dropped. For example, an epoch that ends in
		the last t secs but doesn't start in the last t secs will never 
		get a chance to be part of the most_recent_epochs group. 
		So just return all the epochs that *ended* in the last t secs and 
		as a result, one of the assertions in the main routine needs to
		be disabled.
	'''
	return (sno_et, eno_et)
	''' 
		No need to proceed beyond this point. 
		It is far too much detail for this paper.
		Readers will get confused.
	'''
	s1 = set(range(sno_st, eno_st + 1))
	s2 = set(range(sno_et, eno_et + 1))
	s3 = s1.intersection(s2)
	if len(s3) > 0:
		# Some excellent coding here !
		'''
			For a thread of epochs,
			sno_st = line number of first epoch that started between stime_ and stime
			sno_et = line number of first epoch that ended   between stime_ and stime
			eno_st = line number of last  epoch that started between stime_ and stime
			eno_et = line number of last  epoch that ended   between stime_ and stime
		'''
		sno = max(sno_st, sno_et) # sno_st >= sno_et; An epoch in a thread cannot start before the previous one ends
		eno = min(eno_st, eno_et) # eno_st >= eno_et; For the same reason above
		assert sno in s3
		assert eno in s3
		return (sno,eno)
	else:
		return None
	
def cal_cross_thd_dep(pid, args):

	logdir = args[0]
	logfile = args[1]
	global debug
	debug = int(args[2])
	dl = 1
	# You may empty this before every lookup but i don't cuz it can be reused
	recently_touched_addr = {}
	global wpid
	global est
	global lookback_time
	global f_to_lnnums_m
	global f_to_epochs_m
	global datadir
	n_cross = 0	# Uniq deps
	n_self = 0	# Uniq deps
	total_self = 0	# Ep count
	total_cross = 0	# Ep count
	wpid = pid
	BATCH = 10000
	progress = 0
	cross_dep_addrs = set()
	cross_thread_deps_short = {}
	self_thread_deps_short = {}
	cl_overwrites_single_smt = {}
	#if wpid != 2:
	#	sys.exit(0)
	est = ep_stats()
	print "Worker " + str(wpid) + " analyzing " + logfile

	onlyfiles = [f for f in listdir(logdir) if isfile(join(logdir, f)) and 'txt' in f]
	
	# for f in onlyfiles:
		# make_index_by_stime(logdir, f)
		# make_index_by_etime(logdir, f)
		# make_lnmap(logdir, f)

	print \
	''' Core analysis begins here '''
	'''
    Added feature to detect and report cross thread dependencies
    on NVM addresses. It is a completely parallel algorithm.
    
    For each guest thread T, we iterate through all epochs in that thread.
    - For each epoch E in T, we maintain a global cache C of all epochs that started and
      ended between X and (X - t) secs in any guest thread.
      ... X is that starting time of the epoch E under consideration
          and t is configurable, preferably 50 usecs.
    - Then for each NVM addr A in E, we search C to find the most recent
      epoch E' that dirtied A. If E' is in T, it is a self-dependency else
      it is a cross-thread dependency.

	'''
	with open(logdir + '/' + logfile, 'r') as fp:
		#if debug > 0:
		fo = open(logdir + "/deps-" + logfile.split('.')[0] + "-" + str(lookback_time) + "-us", 'w')
		for lno,l in enumerate(fp):

			if 'PM_TX' in l:
				continue
				
			progress += 1
			if (progress % BATCH) == 0:
				print "Worker", str(wpid),"finished",str("{:,}".format(progress))," epochs"

			try:
				ep_addr  = l.split(';')[1].split(',')
				self_writers = l.split(';')[2].split(',')
				assert len(ep_addr) == len(self_writers)
				ep_summ  = l.split(';')[3] # this may fail due to out-range index
				stime    = est.get_stime_from_str(ep_summ)
				etime    = est.get_etime_from_str(ep_summ)
			except:
				continue

			if debug > dl:
				print '>>>>',lno+1,stime, etime, ep_addr

			for f in onlyfiles:

				#t = find_recent_past_ep(f, stime - lookback_time, stime)
				# Find epochs that ended before the current epoch in the last lookback_time secs
				t = find_recent_past_ep(f, etime - lookback_time, etime)
				if t is not None:
					sno = t[0]
					eno = t[1]
					if f == logfile:
						if eno >= lno + 1:
							print sno, eno, lno + 1, f, f_to_epochs_etime_m[f]
							assert eno < lno + 1
					
					'''
						We're finding all epochs in (X - t) secs identified
						by line number (lno) in a per-thread log where each line
						is one epoch. The asserts check if the epoch is really
						in the interval (X - t) secs.
					'''
					# print sno,'-',eno, f_to_lnnums_m[f][sno][1][0], f_to_lnnums_m[f][eno][1][1],f
					# start and end times of left  most epoch falling in the interval (X - t) secs
					# Disabled : assert stime - lookback_time <= f_to_lnnums_m[f][sno][1][0] and f_to_lnnums_m[f][sno][1][1] <= stime
					# start and end times of right most epoch falling in the interval (X - t) secs
					# Disabled : assert stime - lookback_time <= f_to_lnnums_m[f][eno][1][0] and f_to_lnnums_m[f][eno][1][1] <= stime	
					

					if debug > dl:
						print sno, etime - lookback_time, f_to_lnnums_m[f][sno][1], etime
						print eno, etime - lookback_time, f_to_lnnums_m[f][eno][1], etime
						
					# Only assert the end time of the right most epoch is within the desired interval
					assert (etime - lookback_time <= f_to_lnnums_m[f][sno][1][1] and f_to_lnnums_m[f][sno][1][1] < etime)
					assert (etime - lookback_time <= f_to_lnnums_m[f][eno][1][1] and f_to_lnnums_m[f][eno][1][1] < etime)
					for ln in range(sno, eno + 1):
						if ln not in f_to_lnnums_m[f]:
							continue

						l_addr  = f_to_lnnums_m[f][ln][0]
						tmstmp  = f_to_lnnums_m[f][ln][1]
						other_writers = f_to_lnnums_m[f][ln][2]
						assert len(l_addr) == len(other_writers)
						# tmstmp[0] Start time of an epoch
						# tmstmp[1] End time of an epoch
						for i in range(0, len(l_addr)):
							addr = l_addr[i]
							o_wrt = other_writers[i]
							if addr not in recently_touched_addr:
								recently_touched_addr[addr] = (tmstmp[0], tmstmp[1], f, ln, o_wrt)
							else:
								''' Temporary fix for carelessness in nstore. TODO : Remove later '''
								a,xxx = tmstmp[1], tmstmp[0]
								c,xxx = recently_touched_addr[addr][1],recently_touched_addr[addr][0]
								''' Last-writer-epoch owns the cache line. I think this is correct '''
								# if (tmstmp[0], tmstmp[1], f, ln) > recently_touched_addr[addr]:
								if a > c:
									recently_touched_addr[addr] = (tmstmp[0], tmstmp[1], f, ln, o_wrt)
								# This tuple comparison is the key for this entire algorithm to work
								'''
									A key assumption that makes this work is that epochs that race
									for NVM addresses will be rare or non-existent, which means dependent epochs 
									will not race and strictly have a happens before relationship 
									
									NOTE : This assumption breaks when authors don't bother to carefully
									issue fences. For eg, at the end of a txn PMFS and nstore don't bother
									to fence their writes to NVM leading to long epochs. This messes with my
									tools.
								'''
			''' 
				What we've done so far is form a list of NVM addresses
				dirtied by all threads in the last t micro-seconds.
				This list also identifies the last epoch to dirty the addr.
			'''
			
			nprint = {}
			for ea in ep_addr:
				nprint[ea] = 0
				
			cross_thread_deps = set()
			self_thread_deps  = set()
			my_self = 0
			my_cross = 0
			for i in range(0, len(ep_addr)):
				ea = ep_addr[i]
				s_wrt = self_writers[i]
				if ea in recently_touched_addr:
					# Asserting that the starting time of last owning epoch is within X & (X - t) secs - GOOD !
					# b0 = (stime - lookback_time <= recently_touched_addr[ea][0] and recently_touched_addr[ea][0] <= stime)
					# Asserting that the ending time of last owning epoch is within X & (X - t) secs - GOOD !
					# b1 = (etime - lookback_time <= recently_touched_addr[ea][1] and recently_touched_addr[ea][1] < etime)
					# if not b1:
					#	continue
					# IF COMMENTING THIS, MAKE SURE TO CLEAR THE RECENTLY_USED_ADDR CACHE !!!!!
						
					if nprint[ea] == 0 and debug > 1:
							# fo.write('>>>> ' + str(lno+1) + ' ' + str(stime - lookback_time) + ' ' + str(stime) + ' ' + str(ep_addr) + '\n')
							nprint[ea] = 1

					ownership = "deadbeef"
					f,ln,w = recently_touched_addr[ea][2], recently_touched_addr[ea][3], recently_touched_addr[ea][4]
					if logfile != f:
						my_cross = 1
						ownership = "cross_thread"
						if (f,ln,ea) not in cross_thread_deps and debug > 0:
							cross_thread_deps.add((f,ln,ea))
							if debug > 0: # d = 1
								# The difference between lno+1 and ln gives the reuse-distance of a cache-line 
								# in terms of epochs
								fo.write(ownership + ' ' + str(ea) + ' (' + str(s_wrt) + ',' + str(lno+1) + ') => ' + str(ea) + ' (' + str(w) + ',' + str(f) + ',' + str(ln) + ')\n')
								# W happened before s_wrt
								tstr = str(s_wrt) + ' => ' + str(w) + ' '
								if tstr in cross_thread_deps_short:
									cross_thread_deps_short[tstr] += 1
								else:
									cross_thread_deps_short[tstr] = 1
							n_cross += 1
					else:
						ownership = "self_thread"
						my_self = 1
						if (f,ln,ea) not in self_thread_deps and debug > 0:
							self_thread_deps.add((f,ln,ea))
							if debug > 0:
								fo.write(ownership + ' ' + str(ea) + ' (' + str(s_wrt) + ',' + str(lno+1) + ') => ' + str(ea) + ' (' + str(w) + ',' + str(f) + ',' + str(ln) + ')\n')
								# W happened before s_wrt
								
								if ea not in cl_overwrites_single_smt:
									cl_overwrites_single_smt[ea] = 0
								cl_overwrites_single_smt[ea] += 1
								
								tstr = str(s_wrt) + ' => ' + str(w) + ' '
								if tstr in self_thread_deps_short:
									self_thread_deps_short[tstr] += 1
								else:
									self_thread_deps_short[tstr] = 1
							n_self += 1 # This is the count of how many addresses
										# an epoch has in common with previous epochs
										# on the same thread

			recently_touched_addr = {} # Not needed if we do time-intv check above b1, b0
			if my_self == 1:
				total_self += 1 # This is a count of number of epochs that have at least
								# one address in common with some past epoch on the same
								# thread in 50 us
			if my_cross == 1:
				total_cross += 1
				
			my_self = 0 # needed ?
			my_cross = 0 # needed ?

						# fantastic code, excellent use of data structures
						# excellent use of bisect algo, python tuple comparison features
						# excellent use of python set, and type-indenpendence features !
					
			
			'''
				What we've done so far is to list self- and cross- thread
				dependencies in the last X usecs using a cache of NVM addresses
				that is updated for each epoch and keeps track of the most
				recent owner epoch. Then we simply check this cache for the most
				recent owner epoch in a different SMT context !
			'''
	if debug > 0: # d = 1
		fo.write("\n\n Summary of cross dependencies \n\n")
		for k,v in cross_thread_deps_short.items():
			fo.write(str(k) + ':' + str(v) + ':' + str("cross") + '\n')
		
		
		fo.write("\n\n Summary of self dependencies \n\n")
		for k,v in self_thread_deps_short.items():
			fo.write(str(k) + ':' + str(v) + ':' + str("self") + '\n')

	# print logfile, "n_cross=", n_cross," n_self=", n_self
	print logfile, "(CROS_DEPS) n_cross =", n_cross #, sorted(list(cross_dep_addrs)) # Printed to screen
	print logfile, "(SELF_DEPS) n_self  =", n_self #, sorted(list(cross_dep_addrs))   # Printed to screen
	fo.write("\n\n TOTAL_CROS_DEPS = " + str(n_cross))
	fo.write("\n\n TOTAL_SELF_DEPS = " + str(n_self))

	# Report this. This is what we want.
	print logfile, "(CROS_EPOS) total_cross =", total_cross #, sorted(list(cross_dep_addrs)) # Printed to screen
	print logfile, "(SELF_EPOS) total_self  =", total_self #, sorted(list(cross_dep_addrs))   # Printed to screen
	fo.write("\n\n TOTAL_CROS_EPOS = " + str(total_cross))
	fo.write("\n\n TOTAL_SELF_EPOS = " + str(total_self))

	print "Worker", str(wpid),"finished",str("{:,}".format(progress))," epochs"
	fo.close()
						
# datadir = '/dev/shm/'
# datadir = '/scratch/'
# datadir = '/nobackup/'
datadir = 'results/'
colmap = {}
colmap['etype'] = 0
colmap['epoch_esize'] = 1
colmap['epoch_wsize'] = 2
colmap['epoch_cwsize'] = 3
colmap['epoch_duration'] = 4
colmap['epoch_page_span'] = 6
colmap['epoch_dist_from_mrd'] = 7
colmap['epoch_dist_from_lrd'] = 8
marker = ['ro-', 'bs-', 'g^-', 'kD-']
plain  =   ['r-', 'b-', 'g-', 'k-']
logdir = datadir + args.logdir
cfg = ConfigParser.ConfigParser()
cfg.read('data.ini')

onlyfiles = [f for f in listdir(logdir) if isfile(join(logdir, f)) and '.txt' in f]
pmap = {}
pid = 0
max_pid = 4

for logfile in onlyfiles:
	'''
		Launch a process for each file, which is a thread log with
		the filename and logdir as argument
		
		Laucn a maximum of four processes
		
		Have each process index all files except the one passed to it as argument
		
		I will write the algo later
	'''

	pmap[pid] = Process(target=cal_cross_thd_dep, args=(pid, [logdir, logfile, debug]))
	pmap[pid].start()
	print "Parent started worker ", pid
	pid += 1;
	
	if pid == max_pid:
		print "Max number of processes reached"
		for pid,p in pmap.items():
			print "Parent waiting for worker", pid
			p.join()
		
		pid = 0
	else:
		continue
