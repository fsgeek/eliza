from tentry import tentry
import sys
class ftread:
	
	delim = ':'
	psegment_start = 0x100000000000
	psegment_size  = 0x10000000000
	psegment_end   = psegment_start + psegment_size
	
	def __init__(self, usrargs, sysargs):
		self.pid = sysargs[0]
		self.n = sysargs[3]
		
		self.nti = usrargs.nti
		self.clf = usrargs.clf
		self.st = usrargs.st
		self.ld = usrargs.ld
		
		self.te = tentry()
		
		self.te_pm_ref = list(self.te.get_pm_ref())
		self.other_te_types = list(self.te.get_types() - self.te.get_pm_ref())
		
		self.NTI = list(self.te.n_write_ops)
		self.CLF = list(self.te.flush_ops)
		self.LD  = list(self.te.c_read_ops)
		self.ST  = list(self.te.c_write_ops)
		
		return None
	
	def get_tentry(self, tl):
		assert tl is not None
		te = tentry()
		kernelmode = 1 # Assume kernel trace entry

		''' Are there any trace entries to be avoided ? '''
		if self.nti is False:
			for t in self.NTI:
				if t in tl:
					return None
		if self.clf is False:
			for t in self.CLF:
				if t in tl:
					return None
		if self.st is False:
			for t in self.ST:
				if t in tl:
					return None	
		if self.ld is False:
			for t in self.LD:
				if t in tl:
					return None

		''' Most frequently occuring tentry types '''
		for te_type in self.te_pm_ref:
			if te_type in tl:
				te.set_type(te_type)
				break
		
		''' Rarely occurring tentry types '''
		if te.is_valid() is False:
			for te_type in self.other_te_types:
				if te_type in tl:
					te.set_type(te_type)
					break
				
		if te.is_valid() is False:
			return None

		l = tl.split()
		l0 = l[0].split('-')
		te.set_tid(int(l0[len(l0)-1]))
		if te.get_tid() % self.n != self.pid:
			del te
			return None
		try:	
			tmp_time = l[3].split(':')[0].split('.')
			te.set_time(int(tmp_time[0])*1000000 + int(tmp_time[1]))
			te.set_callee('null')
			
			caller = l[4].split(':')[0]
			if caller is 'tracing_mark_write':
				''' This is user mode trace entry '''
				kernelmode = 0
				caller = l[4][::-1].split(':')[1][::-1]

			te.set_caller(caller)
			
			if te.need_arg():

				__l = l[5].split(':')	
				if kernelmode == 0:
					''' All usermode PM accesses must be within this 
					    range since we map PM at psegment_start.
					'''
					if not (self.psegment_start <= int(__l[1],16) and \
							int(__l[1],16) <= self.psegment_end):
						del te
						return None

				te.set_addr(__l[1])
				te.set_size(int(__l[2]))

				if (te.is_movnti() is True) or (te.is_flush() is True):
					te.set_pc(int(__l[5]))
				else:
					te.set_pc(int(__l[4]))
		except:
			print te.te_list()
			sys.exit(0)
		#else:
		#	te.set_callee(l[4])
			# te.set_caller(l[5].split('-')[1])
					
		return te
