#! /usr/bin/env python

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

# You should create a ~/.httpovclient/prefs containing at least a
# HP_SERVER="<theserver>" entry.

# When changing the Python 2.4 client, make sure it still works
# with Python 2.4 afterwards.

import urllib2
import os
import sys
import platform
import tempfile
import signal
import shutil
import datetime
import time
import atexit
import zipfile
import subprocess
import socket
import threading
try:
	import pwd
	haspwd = True
except ImportError:
	haspwd = False
	pass
try:
	import grp
	hasgrp = True
except ImportError:
	hasgrp = False
	pass

import httplib

# These settings can be overridden in ~/.httpovclient/prefs

HP_SERVER=""
HP_PASSWORD="flimpaflump"
HP_POV="povray"
HP_POVDIR=""
HP_VERURL="http://columbiegg.com/httpov/latest/"
HP_VERPER=259200
HP_TRYTIMES=10
HP_GROUP=""

sleepseed=2
sleepmax=300
nicelevel=5

# These settings can be overridden in the global config

HP_USER=""

# Read global config

try:
	config = open("/etc/httpovclient.conf", "r")
except IOError:
	pass
else:
	execfile("/etc/httpovclient.conf")
	#hpreadconfig(config)
	# Todo: Proper parsing instead of sourcing

# Startup checks

#Dropping privileges
#Used with minimal modifications from
#http://antonym.org/2005/12/dropping-privileges-in-python.html
#by Gavin Baker
#License: Unknown

def hpdroppriv(uid_name):

	# Get the uid/gid from the name
	running_uid = pwd.getpwnam(uid_name)[2]
	running_gid = pwd.getpwnam(uid_name)[3]


	# Try setting the new uid/gid
	try:
		os.setgid(running_gid)
	except OSError, e:
		print('Could not set effective group id: %s' % e)

	try:
		os.setgroups([running_gid])
	except OSError, e:
		print('Could not set groups: %s' % e)

	try:
		os.setuid(running_uid)
	except OSError, e:
		print('Could not set effective user id: %s' % e)

	# Ensure a very convervative umask
	new_umask = 077
	old_umask = os.umask(new_umask)
	print('drop_privileges: Old umask: %s, new umask: %s' % (oct(old_umask), oct(new_umask)))

	final_uid = os.getuid()
	final_gid = os.getgid()
	print('drop_privileges: running as %s/%s' % (pwd.getpwuid(final_uid)[0], grp.getgrgid(final_gid)[0]))

if hasattr(os, 'getuid'):
	if os.getuid() == 0:
		if HP_USER != "":
			print "Started as root - changing to '"+HP_USER+"'."
			try:
				uid = pwd.getpwnam(HP_USER)[2]
				hpdroppriv(HP_USER)
			except KeyError:
				print "HTTPov client: User not found"
				sys.exit(1)

		else:
			print "HTTPov client: Running as root is not supported."
			print "HTTPov client: Please define HP_USER in global config file."
			sys.exit(1)
	else:
		starter = pwd.getpwuid(os.getuid())[0]
		if HP_USER != "" and starter != HP_USER:
			print "Warning: Starting user is not globally configured running user ("+starter+" / "+HP_USER+")"
			print "Warning: Continuing as user "+starter
		HP_USER = starter
else:
	print "Notice: os.getuid() not supported, not checking user."


HP_INITFAIL = 0
HP_HOME = os.path.expanduser("~"+HP_USER)

config = False
try:
	cname = os.path.join(HP_HOME, ".httpovclient", "prefs")
	config = open(cname, "r")
except IOError:
	try:
		cname = os.path.join(HP_HOME, "_httpovclient", "prefs.txt")
		config = open(cname, "r")
	except IOError:
		pass

if(config):
	config.close()
	execfile(cname)
	#hpreadconfig(config)
	# Todo: Proper parsing instead of sourcing

if len(sys.argv) > 1:
	if sys.argv[1].isdigit():
		HP_CID = sys.argv[1]
	else:
		print "Client ID must be a positive integer."
		sys.exit(1)
else:
	HP_CID = os.getpid()

# Client script settings

HP_CLIENT = platform.node()+":"+str(HP_CID)
HP_VERSION = "2.2"
HP_PID = os.getpid()
HP_WD = tempfile.mkdtemp(prefix='HTTPov_')
HP_CMDFILE = "httpovclient.commands"
HP_ABORTFILE = "httpovclient.abort"
HP_STDARGS = "client="+HP_CLIENT+"&version="+HP_VERSION
if HP_GROUP != "":
	print "This client belong to the group '"+HP_GROUP+"'"
	HP_STDARGS = HP_STDARGS+"&cgroup="+HP_GROUP

sleeptime = sleepseed
aloopcount = 0
aloopgo = False

# Function definitions

def hpactiveloop_start():
	global aloopcount, aloopgo
	aloopcount = 60
	aloopgo = True

def hpactiveloop_stop():
	global aloopgo
	aloopgo = False

def hpactiveloop():
	global aloopcount
	while True:
		if aloopgo:
			aloopcount = aloopcount - 1
			if aloopcount == 0:
				try:
					infile = urllib2.urlopen("http://"+HP_SERVER+"/httpov.php?command=active&job="+str(job)+"&batch="+str(batch)+"&"+HP_STDARGS)
				except urllib2.URLError:
					pass
				aloopcount = 60
			time.sleep(1)

def hpfindexe(file, dir):
	if(dir != ""):
		if os.path.exists(dir+file) and os.access(dir+file, os.X_OK):
				return dir+file
	else:
		for path in os.environ["PATH"].split(os.pathsep):
			fullfile = os.path.join(path, file)
			if os.path.exists(fullfile) and os.access(fullfile, os.X_OK):
				return fullfile

	return None

# Further startup checks

HP_POV = hpfindexe(HP_POV, HP_POVDIR)
if HP_POV == None:
	print "Povray binary not found."
	HP_INITFAIL = 1

if HP_SERVER == "":
	print "No server specified."
	HP_INITFAIL = 1

if HP_INITFAIL == 1:
	print "Fatal error."
	sys.exit(1)

HP_PWD = os.getcwd()

os.chdir(HP_WD)

# Function definitions

class hpunzip:

# Used with minimal modifications from
# http://code.activestate.com/recipes/252508-file-unzip/
# by Doug Tolton
# License: PSF

	def __init__(self, verbose = False, percent = 10):
		self.verbose = verbose
		self.percent = percent
	
	def extract(self, file, dir):
		if not dir.endswith(':') and not os.path.exists(dir):
			os.mkdir(dir)

		zf = zipfile.ZipFile(file)

		# create directory structure to house files
		self._createstructure(file, dir)

		num_files = len(zf.namelist())
		percent = self.percent
		divisions = 100 / percent
		perc = int(num_files / divisions)

		# extract files to directory structure
		for i, name in enumerate(zf.namelist()):

			if self.verbose == True:
				print "Extracting %s" % name
			elif perc > 0 and (i % perc) == 0 and i > 0:
				complete = int (i / perc) * percent
				print "%s%% complete" % complete

			if not name.endswith('/'):
				outfile = open(os.path.join(dir, name), 'wb')
				outfile.write(zf.read(name))
				outfile.flush()
				outfile.close()


	def _createstructure(self, file, dir):
		self._makedirs(self._listdirs(file), dir)


	def _makedirs(self, directories, basedir):
		""" Create any directories that don't currently exist """
		for dir in directories:
			curdir = os.path.join(basedir, dir)
			if not os.path.exists(curdir):
				os.mkdir(curdir)

	def _listdirs(self, file):
		""" Grabs all the directories in the zip structure
		This is necessary to create the structure before trying
		to extract the file to it. """
		zf = zipfile.ZipFile(file)

		dirs = []

		for name in zf.namelist():
			if name.endswith('/'):
				dirs.append(name)

		dirs.sort()
		return dirs

def hprzip(zipf, directory):
	try:
		# Modern Python seem to prefer this, and even
		# require it in order to create proper archives.
		# 2.4 doesn't.
		zipf.write(directory)
	except IOError:
		pass
	for item in os.listdir(directory):
		if os.path.isfile(os.path.join(directory, item)):
			zipf.write(os.path.join(directory, item))
		elif os.path.isdir(os.path.join(directory, item)):
			hprzip(zipf, os.path.join(directory, item))

def hpdate():
	return str(datetime.datetime.now().ctime())

def hpcheckfile(filename):
	try:
		checked = open(os.path.join(HP_WD, filename), 'rb')
		checked.close()
		return True
	except IOError:
		return False

def hpcheckabort():
	if hpcheckfile(HP_ABORTFILE) == True:
			sys.exit(0)

def hpabort(signal, frame):
	try:
		f = open(os.path.join(HP_WD, HP_ABORTFILE), 'wb')
		f.write("abort")
		f.close()
		print "HTTPov client abort requested."
	except IOError:
		print "HTTPov client abort request failed!"

def hpcleanup():
	if HP_PWD != "":
		try:
			#This will fail if the client was started by root.
			#However, systems with the pwd module should be
			#able to remove HP_WD anyway, and systems without
			#can't start the client as root to begin with.
			os.chdir(HP_PWD)
		except OSError:
			pass
	shutil.rmtree(HP_WD)
	print "HTTPov client exiting."

def hpcheckver():
	global lastcheck

	sinceepoch = int(time.time())
	sincelast = sinceepoch - lastcheck

	if sincelast > HP_VERPER:
		lastcheck = sinceepoch
		try:
			infile = urllib2.urlopen(HP_VERURL+"?version="+HP_VERSION)
		except urllib2.URLError:
			return False
		else:
			commands = infile.readlines()
			infile.close()

			if len(commands) > 0:
				key, value = commands[0].strip().split("=", 1)

				if key == "clientver":
					print
					print "Latest client available: "+value
					print "Find out more at "+HP_VERURL
					print

	return True

def hphello():
	try:
		infile = urllib2.urlopen("http://"+HP_SERVER+"/httpov.php?command=hello&"+HP_STDARGS)
	except urllib2.URLError:
		return False
	else:
		try:
			outfile = open(os.path.join(HP_WD, HP_CMDFILE), 'wb')
		except IOError:
			return False
		else:
			outfile.write(infile.read())
			outfile.close()
		infile.close()
		return True

def hpgetjob():
	try:
		infile = urllib2.urlopen("http://"+HP_SERVER+"/httpov.php?command=getjob&"+HP_STDARGS)
	except urllib2.URLError:
		return False
	else:
		try:
			outfile = open(os.path.join(HP_WD, HP_CMDFILE), 'wb')
		except IOERROR:
			return False
		else:
			outfile.write(infile.read())
			outfile.close()
		infile.close()
		return True

def hppostbatch(filename):
	try:
		infile = open(filename, 'rb')
	except IOError:
		print "File error"
		sys.exit
	else:
		filedata = infile.read()
		infile.close()

		fullstart = "_frame_%08d" % int(startframe)
		if sliceno == "":
			filename = name+fullstart+".zip"
			query = "/httpov.php?command=postbatch&job="+str(job)+"&batch="+str(batch)+"&"+HP_STDARGS
		else:
			fullslice = "_%04d" % int(sliceno)
			filename = name+fullstart+fullslice+".zip"
			query = "/httpov.php?command=postbatch&job="+str(job)+"&batch="+str(batch)+"&"+HP_STDARGS


		boundary = '---------HTTPov_file_upload_boundary_$'
		crlf = '\r\n'
		bodyparts = []
		bodyparts.append('--' + boundary)
		bodyparts.append('Content-Disposition: form-data; name="filedata"; filename="%s"' % filename)
		bodyparts.append('Content-Type: %s' % 'application/octet-stream')
		bodyparts.append('')
		bodyparts.append(filedata)
		bodyparts.append('--' + boundary + '--')
		bodyparts.append('')
		body = crlf.join(bodyparts)
		content_type = 'multipart/form-data; boundary=%s' % boundary

		h = httplib.HTTP(HP_SERVER)
		try:
			h.putrequest('POST', query)
			h.putheader('host', HP_SERVER)
			h.putheader('content-type', content_type)
			h.putheader('content-length', str(len(body)))
			h.endheaders()
			h.send(body)
			errcode, errmsg, headers = h.getreply()
		except socket.error:
			h.close()
			return False
		h.close()
		if errcode == 200:
			return True
		else:
			return False

def hpupsleep(lsleeptime):
	lsleeptime = lsleeptime * 2
	if lsleeptime > sleepmax:
		lsleeptime = sleepmax
	return lsleeptime

def hpreadcommands():
	global jobmessage, sleeptime, job, name, frames, batch
	global startframe, stopframe, sliceno, startrow, endrow
	global render, hp_sleep

	try:
		cmdfile = open(os.path.join(HP_WD, HP_CMDFILE), 'rb')
	except IOError:
		return False
	else:
		commands = cmdfile.readlines()

		for i in range(len(commands)):
			key, value = commands[i].strip().split("=", 1)

			if key == "command":
				if value == "getbatch":
					hp_sleep = 0
					junk, job = commands[i+1].strip().split("=", 1)
					junk, name = commands[i+2].strip().split("=", 1)
					junk, frames = commands[i+3].strip().split("=", 1)

				if value == "sleep":
					if jobmessage == 1:
						print hpdate()+": Server found, but no job is available."
						jobmessage = 0

				if value == "getjob":
					job = 0

				if value == "render":
					junk, batch = commands[i+1].strip().split("=", 1)
					junk, startframe = commands[i+2].strip().split("=", 1)
					junk, stopframe = commands[i+3].strip().split("=", 1)
					if(len(commands) > 4):
						junk, sliceno = commands[i+4].strip().split("=", 1)
						junk, startrow = commands[i+5].strip().split("=", 1)
						junk, endrow = commands[i+6].strip().split("=", 1)
					else:
						sliceno = ""
						startrow = ""
						endrow = ""
					render = 1

			if key == "message":
				print "Server message: "+value

			if key == "error":
				print "Server error: "+value
				sys.exit(1)

			i = i + 1

		if hp_sleep == 1:
			hpsleep(sleeptime)
			sleeptime = hpupsleep(sleeptime)

def hpsleep(sleeptime):
	hpcheckver()
	hpcheckabort()
	print hpdate()+": Sleeping "+str(sleeptime)+" seconds"
	if sleeptime > 10:
		sleeps = sleeptime / 10
		remainder = sleeptime % 10
		for junk in range(sleeps):
			time.sleep(10)
			hpcheckabort()

		time.sleep(remainder)
	else:
		time.sleep(sleeptime)

def hpgetbatch():
	try:
		infile = urllib2.urlopen("http://"+HP_SERVER+"/httpov.php?command=getbatch&job="+job+"&"+HP_STDARGS)
	except urllib2.URLError:
		return False
	else:
		try:
			outfile = open(os.path.join(HP_WD, HP_CMDFILE), 'wb')
		except IOError:
			return False
		else:
			outfile.write(infile.read())
			outfile.close()
		infile.close()
		return True

def hpabortbatch():
	try:
		infile = urllib2.urlopen("http://"+HP_SERVER+"/httpov.php?command=abortbatch&job="+job+"&batch="+batch+"&"+HP_STDARGS)
	except urllib2.URLError:
		return False
	else:
		try:
			outfile = open(os.path.join(HP_WD, HP_CMDFILE), 'wb')
		except IOError:
			return False
		else:
			outfile.write(infile.read())
			outfile.close()
		infile.close()
		return True

def hpgetdata():
	try:
		infile = urllib2.urlopen("http://"+HP_SERVER+"/jobs/"+name+".zip")
	except IOError:
		return False
	else:
		try:
			outfile = open(os.path.join(HP_WD, name+".zip"), 'wb')
		except IOError:
			return False
		else:
			outfile.write(infile.read())
			outfile.close()
		infile.close()
		return True

def hppanic():
	print hpdate()+": Server communication failed!"
	infile = urllib2.urlopen("http://"+HP_SERVER+"/httpov.php?command=hello&"+HP_STDARGS)
	infile.close()
	sys.exit(1)

def hptry(tryfunc, argument = None):
	trytime = 1
	trytimes = HP_TRYTIMES
	trymessage = 1
	if trytimes == 0:
		while 1:
			if argument == None:
				tryresult = tryfunc()
			else:
				tryresult = tryfunc(argument)
			if tryresult:
				return True
			else:
				if trymessage != 0:
					print "Network trouble."
					trymessage = 0
				print "Retrying until successful"
				hpsleep(trytime)
				trytime = hpupsleep(trytime)
	else:
		while trytimes != 0:
			trytimes = trytimes -1
			if argument == None:
				tryresult = tryfunc()
			else:
				tryresult = tryfunc(argument)
			if tryresult:
				return True
			else:
				if trymessage != 0:
					print "Network trouble."
					trymessage = 0
				print "Retrying: "+str(trytimes)
				hpsleep(trytime)
				trytime = hpupsleep(trytime)
	hppanic()

# Main loop starts here

signal.signal(signal.SIGINT, hpabort)
atexit.register(hpcleanup)

povstatus = ""
lastcheck = 0
unzipper = hpunzip()
render = 0
print
print hpdate()+": HTTPov client "+HP_VERSION+" starting."
hpcheckver()

t = threading.Thread(target=hpactiveloop)
t.daemon = True
t.start()

if hasattr(os, 'nice'):
	os.nice(int(nicelevel))

while HP_PASSWORD != "changeme":
	jobmessage = 1
	hp_sleep = 1

	# Job fech loop

	while hp_sleep == 1:
		hptry(hpgetjob)

		i = 0

		hpreadcommands()

		hpcheckabort()

	# Get and decompress job

	sleeptime = sleepseed
	print hpdate()+": Fetching data for job "+job+" ("+name+")"
	
	hptry(hpgetdata)
	
	print "Decompressing data for job "+job+" ("+name+")"
	unzipper.extract(name+'.zip', HP_WD)
	previous = os.getcwd()
	try:
		os.chdir(name)
	except OSError:
		print "\nCould not find the decompressed job."
		print "Is the directory name the same as the archive name?"
		sys.exit(1)

	# Batch fetch loop

	while job != 0:
		print hpdate()+": Fetching batch for job "+job+" ("+name+")"
		hptry(hpgetbatch)

		hpreadcommands()

		if render == 1:

			if platform.system() == 'Windows':
				argRENDER = '/RENDER'
				argO = ''
				argEXIT = '/EXIT'
			else:
				argRENDER = ''
				argO = '+O'
				argEXIT = ''

			print "Starting render job:"
			print "Batch:     "+batch
			if sliceno == "":
				print "Startframe "+startframe
				print "Stopframe  "+stopframe
			else:
				print "Frame: "+startframe
				print "Slice: "+sliceno

			if sliceno == "":
				args = ["-D", "pov.ini", argRENDER, argO+os.path.join(HP_WD, str(name), str(name)+"_"), "+SF"+str(startframe), "+EF"+str(stopframe), "+FN", argEXIT]
			else:
				args = ["-D", "pov.ini", argRENDER, argO+os.path.join(HP_WD, str(name), str(name)+"_"), "+SF"+str(startframe), "+EF"+str(stopframe), "+SR"+str(startrow), "+ER"+str(endrow), "+FP", argEXIT]

			pov = [HP_POV]
			pov.extend(args)
			hpactiveloop_start()
			try:
				batchreport = open("batchreport.txt", "wb")
				try:
					povproc = subprocess.Popen(pov, stdin=subprocess.PIPE, stdout=batchreport, stderr=batchreport)
				except OSError:
					print "Render error!"
					batchreport.close()
					time.sleep(1)
					povstatus = "failed"
				try:
					retval = povproc.wait()
				except OSError:
					batchreport.close()
					time.sleep(1)
					povstatus = "failed"
				batchreport.close()
			except IOError:
				print hpdate()+": Could not create batchreport, exiting!"
				povstatus = "failed"

			hpactiveloop_stop()
			try:
				rptfile = open('batchreport.txt', 'rb')
				inline = rptfile.readline()
				while inline:
					if inline.find('Aborting render') >= 0:
						povstatus = 'failed'
					if inline.find('Parse Error') >= 0:
						povstatus = 'failed'
					inline = rptfile.readline()
				rptfile.close()
			except IOError:
				povstatus = 'failed'

			framereport = ""
			places = str(len(str(frames)))
			if sliceno == "":
				for frame in range(int(startframe), int(stopframe)+1):
					frame = ("%0"+places+"d") % frame
					if hpcheckfile(os.path.join(name, name+"_"+frame+".png")) == True:
						framereport = framereport+name+"_"+frame+".png created.\n"
					else:
						if hpcheckfile(os.path.join(name, name+frame+".png")) == True:
							#pvengine.exe (or Windows) doesn't seem to like a
							#trailing underscore in the file name. Let's add it.
							shutil.move(os.path.join(HP_WD, name, name+frame+".png"), os.path.join(HP_WD, name, name+"_"+frame+".png"))
							framereport = framereport+name+"_"+frame+".png created.\n"
						else:
							framereport = framereport+name+"_"+frame+".png is missing!\n"
							povstatus = "failed"

			else:
				fullstartframe = ("%0"+places+"d") % int(startframe)
				if hpcheckfile(os.path.join(name, name+"_"+fullstartframe+".ppm")) == True:
					fullslice = "%04d" % int(sliceno)
					framereport = framereport+name+"_"+fullstartframe+"_"+fullslice+".ppm created.\n"
				else:
					if hpcheckfile(os.path.join(name, name+fullstartframe+".ppm")) == True:
						#pvengine.exe (or Windows) doesn't seem to like a
						#trailing underscore in the file name. Let's add it.
						shutil.move(os.path.join(HP_WD, name, name+fullstartframe+".ppm"), os.path.join(HP_WD, name, name+"_"+fullstartframe+".ppm"))
						fullslice = "%04d" % int(sliceno)
						framereport = framereport+name+"_"+fullstartframe+"_"+fullslice+".ppm created.\n"
					else:
						framereport = framereport+name+"_"+fullstartframe+".ppm is missing!\n"
						povstatus = "failed";

			if povstatus == "failed":
				hptry(hpabortbatch)
				try:
					batchreport = open("batchreport.txt", "rb")
					print batchreport.read()
					batchreport.close()
				except IOError:
					print hpdate()+": Could not read batchreport, exiting!"
					sys.exit(1)

				print
				if framereport != "":
					print framereport
				try:
					batchreport = open("batchreport.txt", "ab")
					batchreport.write(framereport)
					batchreport.close()
				except IOError:
					print hpdate()+": Could not write batchreport, exiting!"

				print hpdate()+": Povray failed, client aborting."
				sys.exit(1)
			else:
				povstatus = ""
				if framereport != "":
					print framereport

				fullstart = "%08d" % int(startframe)
				os.mkdir(name+"_frame_"+fullstart)
				copyreport = 1
				for frame in range(int(startframe), int(stopframe)+1):
					frame = ("%0"+places+"d") % frame
					if sliceno == "":
						shutil.move(name+"_"+frame+".png", name+"_frame_"+fullstart)
						if copyreport:
							shutil.move("batchreport.txt", name+"_frame_"+fullstart)
							copyreport = 0
					else:
						fullslice = "%04d" % int(sliceno)
						shutil.move(name+"_"+frame+".ppm", os.path.join(name+"_frame_"+fullstart, "slice_"+fullslice+".ppm"))
						shutil.move("batchreport.txt", os.path.join(name+"_frame_"+fullstart, "batchreport_"+fullslice+".txt"))

				print hpdate()+": Compressing data for job "+str(job)+" ("+name+")"
				if sliceno == "":
					zf = zipfile.ZipFile(name+"_frame_"+fullstart+".zip", "w")
					hprzip(zf, name+"_frame_"+fullstart)
					zf.close()
					print hpdate()+": Uploading batch data"
					hptry(hppostbatch, name+"_frame_"+fullstart+".zip")
					os.unlink(name+"_frame_"+fullstart+".zip")
					shutil.rmtree(name+"_frame_"+fullstart)

				else:
					zf = zipfile.ZipFile(name+"_frame_"+fullstart+"_"+fullslice+".zip", "w")
					hprzip(zf, name+"_frame_"+fullstart)
					zf.close()
					print hpdate()+": Uploading batch data"
					hptry(hppostbatch, name+"_frame_"+fullstart+"_"+fullslice+".zip")
					os.unlink(name+"_frame_"+fullstart+"_"+fullslice+".zip")
					shutil.rmtree(name+"_frame_"+fullstart)
				print
		else:
			print hpdate()+": No batch received."
			job = 0

		if hpcheckfile(HP_ABORTFILE) == True:
			job = 0

	print hpdate()+": Deleting job data"
	os.chdir(previous)
	shutil.rmtree(name)
	os.unlink(name+".zip")
	os.unlink(HP_CMDFILE)
	hpcheckabort()
	sleeptime = sleepseed

if HP_PASSWORD == "changeme":
	print "Change the password."
