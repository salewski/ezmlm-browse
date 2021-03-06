import email
import operator
import os
import re
import rfc822
import string
import time
import types

import config
from globals import *

_rx_thread = re.compile(r'^(\d+):(\S+) \[(\d+)\] (.+)$')
_rx_message = re.compile(r'^(\d+):(\d+):(\S+) (.+)$')
_rx_endofhdr = re.compile(r'^\s*$')
_rx_id = re.compile(r'(<[^>]+>)')
_rx_ws = re.compile(r'\s+')
_rx_header = re.compile(r'^(\S+):\s*(.*)$')
_rx_from1 = re.compile(r'(<[^>]+@[^>@]+>)')
_rx_from2 = re.compile(r'(\([^>]+@[^>@]+\))')
_rx_index = re.compile(r'^(\d+): (\S{20}) (.*)\n\s*([^;]+);(\S{20})\s?(.*)$')

def _in(a, min, max):
	if a > max: return max
	if a < min: return min
	return a

month_names = {
	1: 'January',
	2: 'February',
	3: 'March',
	4: 'April',
	5: 'May',
	6: 'June',
	7: 'July',
	8: 'August',
	9: 'September',
	10: 'October',
	11: 'November',
	12: 'December'
	}

#def _thread_message(id, idmap, nummap, irtmap, replymap, refmap):
def _thread_message(id, idmap, nummap, replymap):
	# result: {replies}
	#try: irt = nummap[irtmap[id]]
	#except KeyError: irt = None
	replies = { }
	for i in replymap[id]:
		num = nummap[i]
		replies[num] = _thread_message(i, idmap, nummap, replymap)
		idmap[num] = None
	#references = [ ]
	#if refmap[id]:
	#	for i in refmap[id]:
	#		if i <> irtmap[id] and nummap.has_key(i):
	#			references.append(nummap[i])
	#followups = [ ]
	#for i in replymap[id]:
	#	if not replymap.has_key(i):
	#		followups.append(nummap[i])
	#return (irt, replies, references, followups)
	return replies

def _process_thread(thread, map):
	list = [ ]
	nums = thread.keys()
	nums.sort()
	for num in nums:
		msg = map[num]
		msg['threads'] = _process_thread(thread[num], map)
		list.append(msg)
	return list

def _open_msg(archdir, num):
	num = '%03d' % int(num)
	f = open(os.path.join(archdir, num[:-2], num[-2:]))
	return email.message_from_file(f)

def _open_subjects(archdir, threadid):
	f = open(os.path.join(archdir, 'subjects', threadid[:2], threadid[2:]))
	subject = f.readline()[21:].strip()
	msgs = [ _rx_message.match(line) for line in f.readlines() ]
	msgs = [ match.groups() for match in msgs if match ]
	msgs = [ { MSGNUM: int(groups[0]),
			   MONTH: int(groups[1]),
			   AUTHORID: groups[2],
			   AUTHOR: groups[3] }
			 for groups in msgs ]
	return subject, msgs

def _decode_header_part(part, charset):
	if not charset or charset == 'x-unknown':
		charset = config.charsets['default']
	return unicode(part, charset, 'replace')

def _decode_header(header):
	header = email.Header.decode_header(header)
	return u''.join([ _decode_header_part(part, charset)
					 for part,charset in header ])

class EzmlmIndex:
	def __init__(self, listdir):
		self.archdir = os.path.join(listdir, 'archive')
		self.msgs = { }

	def __getitem__(self, key):
		key = int(key)
		try:
			msg = self.msgs[key]
		except KeyError:
			self.populate(key/100)
			msg = self.msgs[key]
		if type(msg[SUBJECT]) is not types.UnicodeType:
			try:
				msg[SUBJECT] = unicode(msg[SUBJECT], 'utf-8')
				msg[AUTHOR] = unicode(msg[AUTHOR], 'utf-8')
			except UnicodeDecodeError:
				email = _open_msg(self.archdir, key)
				msg[SUBJECT] = _decode_header(email['subject'])
				header = email['from']
				m = _rx_from1.search(header)
				if m:
					header = header[:m.start()].rstrip()
				else:
					m = _rx_from1.search(header)
					if m:
						header = (header[:m.start()].rstrip()
								  + ' '
								  + header[m.end():].lstrip())
				msg[AUTHOR] = _decode_header(header)
		return msg

	def populate(self, sub):
		file = open(os.path.join(self.archdir, str(sub), 'index'))
		linepair = file.readline() + file.readline()
		prev_timestamp = 0
		while linepair:
			match = _rx_index.match(linepair.rstrip())
			if match:
				g = match.groups()
				msgnum = int(g[0])
				try:
					timestamp = rfc822.mktime_tz(rfc822.parsedate_tz(g[3]))
				except:
					timestamp = prev_timestamp + 1
				prev_timestamp = timestamp
				localtime = time.localtime(timestamp)
				self.msgs[msgnum] = {
					MSGNUM: msgnum,
					THREADID: g[1],
					SUBJECT: g[2],
					DATE: g[3],
					TIMESTAMP: timestamp,
					AUTHORID: g[4],
					AUTHOR: g[5],
					MONTH: localtime[0] * 100 + localtime[1],
					}
			linepair = file.readline() + file.readline()
		file.close()

class EzmlmArchive:
	def __init__(self, listdir):
		self.headermax = 4096
		self.listdir = listdir
		self.archdir = os.path.join(listdir, 'archive')
		self.months = map(int,
						  os.listdir(os.path.join(self.archdir, 'threads')))
		self.months = filter(lambda a: a >= 190000 and a <= 299999,
							 self.months)
		self.months.sort()
		self.months.reverse()
		self.index = EzmlmIndex(listdir)

		try: prefix = open(os.path.join(listdir, 'prefix')).readline()
		except IOError: prefix = ''
		self.prefix = prefix.strip()

		try: num = open(os.path.join(listdir, 'num')).readline()
		except IOError: num = '0:0'
		num = map(int, num.split(':'))
		self.num = num[0]
		self.kb = num[1] / 4

	def make_reply_subject(self, subject):
		if self.prefix:
			try:
				i = subject.index(self.prefix)
				subject = subject[i + len(self.prefix):].strip()
			except ValueError: pass
		while subject[:3].lower() == 're:':
			subject = subject[3:].strip()
		return 'Re: ' + subject

	def set_months(self, form):
		if not form.has_key(MONTH):
			firstmonth = prevmonth = month = nextmonth = lastmonth = int(self.months[0])
		else:
			firstmonth = int(self.months[-1])
			lastmonth = int(self.months[0])
			month = int(form[MONTH])
			if month > lastmonth or month < firstmonth:
				raise ValueError, "Month value is out of range."
			if month >= lastmonth:
				nextmonth = lastmonth
			else:
				nextmonth = self.months[self.months.index(month)-1]
			if month <= firstmonth:
				prevmonth = firstmonth
			else:
				prevmonth = self.months[self.months.index(month)+1]
		form[FIRSTMONTH] = firstmonth
		form[PREVMONTH] = prevmonth
		form[MONTH] = month
		form[NEXTMONTH] = nextmonth
		form[LASTMONTH] = lastmonth

	def open(self, num):
		return _open_msg(self.archdir, num)

	def month(self, month):
		messages = { }
		for thread in self.threads(month):
			tid = thread[THREADID]
			thread = self.thread(tid)
			subject = thread[SUBJECT]
			for message in thread[MESSAGES]:
				if message[MONTH] == month:
					n = message[MSGNUM]
					message.update(self.index[n])
					messages[n] = message
		numbers = messages.keys()
		numbers.sort()
		return map(operator.getitem, [messages]*len(numbers), numbers)

	def thread(self, threadid):
		if '.' in threadid or '/' in threadid:
			raise ValueError, "Thread ID contains invalid characters"
		subject,list = _open_subjects(self.archdir, threadid)
		for item in list:
			item.update(self.index[item[MSGNUM]])
		subject = list[0][SUBJECT]
		return { SUBJECT: subject, THREADID: threadid, MESSAGES: list }

	def threads(self, month):
		list = [ ]
		path = os.path.join(self.archdir, 'threads', str(month))
		try:
			f = open(path).readlines()
		except IOError:
			f = [ ]
		list = [ _rx_thread.match(line.strip())
				 for line in f ]
		list = [ match.groups()
				 for match in list
				 if match ]
		list = [ {
			MSGNUM: int(match[0]),
			THREADID: match[1],
			MSGCOUNT: int(match[2]),
			SUBJECT: match[3]
			}
				 for match in list ]
		for item in list:
			try:
				item[SUBJECT] = unicode(item[SUBJECT], 'utf-8')
			except UnicodeDecodeError:
				subject,msgs = _open_subjects(self.archdir, item[THREADID])
				if len(msgs) > 0:
					msg = self.index[msgs[0][MSGNUM]]
					item[SUBJECT] = msg[SUBJECT]
		return list

	def search(self, terms):
		terms = _rx_ws.split(terms)
		terms = map(string.lower, terms)
		dir = os.path.join(self.archdir, 'threads')
		threads = [ ]
		for month in self.months:
			month = str(month)
			for line in open(os.path.join(dir, month)).readlines():
				line = line.strip()
				match = _rx_thread.match(line)
				if match:
					groups = match.groups()
					subject = groups[3].lower()
					for term in terms:
						if subject.find(term) < 0: subject = ''; break
					if not subject: continue
					groups = match.groups()
					try:
						m = self.index[int(groups[0])]
					except KeyError:
						pass
					else:
						m[MSGCOUNT] = int(groups[2])
						m[MONTH] = int(month)
						threads.append(m)
		return threads

	def _parse_message(self, num):
		# Result: message-id, in-reply-to, references
		msg = self.open(num)
		messageid = msg['message-id']
		inreplyto = msg['in-reply-to']
		if inreplyto:
			inreplyto = _rx_id.search(inreplyto)
			if inreplyto:
				inreplyto = inreplyto.group(0)
		refs = msg['references'] or []
		if refs:
			refs = _rx_ws.split(refs)
		return (messageid, inreplyto, refs)

	def thread_messages(self, messages):
		messageids = { }
		messagenums = { }
		replies = { }
		inreplytos = { }
		references = { }
		for message in messages:
			msgnum = message[MSGNUM]
			( messageid,inreplyto,refs ) = self._parse_message(msgnum)
			messageids[msgnum] = messageid
			messagenums[messageid] = msgnum
			replies[messageid] = [ ]
			references[messageid] = refs
			if refs and not inreplyto:
				inreplyto = refs[-1]
			if inreplyto:
				if replies.has_key(inreplyto):
					replies[inreplyto].append(messageid)
			inreplytos[messageid] = inreplyto
		#print 'messageids:', messageids
		#print 'messagenums:', messagenums
		#print 'replies:', replies
		#print 'references:', references
		num2msg = { }
		for message in messages:
			num2msg[message[MSGNUM]] = message
		list = { }
		for message in messages:
			msgnum = message[MSGNUM]
			if messageids[msgnum] is not None:
				tmp = _thread_message(messageids[msgnum],
									  messageids, messagenums, replies)
									  #inreplytos, replies, references)
				list[msgnum] = tmp
		return _process_thread(list, num2msg)

	def author(self, authorid):
		path = os.path.join(self.archdir, 'authors',
							authorid[:2], authorid[2:])
		index = open(path)
		index.readline()
		msgs = [ ]
		index = index.readlines()
		index.reverse()
		for line in index:
			m = _rx_message.match(line.strip())
			if m:
				groups = m.groups()
				m = self.index[int(groups[0])]
				m[MONTH] = int(groups[1])
				msgs.append(m)
		name = msgs[0][AUTHOR]
		return { AUTHORID: authorid, AUTHOR: name, MESSAGES: msgs }
