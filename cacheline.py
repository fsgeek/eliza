class cacheline:
	"""Cacheline"""
	cstates = set(['clean', 'dirty', 'invalid'])
	
	def __init__(self, addr):
		self.addr = addr
		self.state = 'invalid'
		self.dbufs = set()
		assert self.addr is not None
		assert self.state in self.cstates
		
	def dirty_all(self):
		self.dbufs.add(8)
			
	def dirty(self, b_idx):
		assert b_idx > -1 and b_idx < 8
		self.dbufs.add(b_idx)
		
	def get_dirtyness(self):
		if 8 in self.dbufs:
			return 8
		else:
			return len(self.dbufs)
			
	def get_addr(self):
		return self.addr
	
	def get_state(self):
		assert self.state in self.cstates
		return self.state
		
	def set_state(self, state):
		assert state in self.cstates
		assert self.state in self.cstates
		self.state = state