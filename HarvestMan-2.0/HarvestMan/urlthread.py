# -- coding: latin-1
""" urlthread.py - Url thread downloader module.
    Has two classes, one for downloading of urls and another
    for managing the url threads.

    This module is part of the HarvestMan program.

    Author: Anand B Pillai <anand at harvestmanontheweb.com>
    
    Modification History

    Jan 10 2006  Anand  Converted from dos to unix format (removed Ctrl-Ms).
    Jan 20 2006  Anand  Small change in printing debug info in download
                        method.

    Mar 05 2007  Anand  Implemented http 304 handling in notify(...).

    Apr 09 2007  Anand  Added check to make sure that threads are not
                        re-started for the same recurring problem.
    
    Copyright (C) 2004 Anand B Pillai.

"""

__version__ = '2.0 b1'
__author__ = 'Anand B Pillai'

import os, sys
import math
import time
import threading
import copy
import random

from collections import deque
from Queue import Queue, Full, Empty
from common.common import *

class HarvestManUrlThreadInterrupt(Exception):
    """ Interrupt raised to kill a harvestManUrlThread class's object """

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return str(self.value)

class HarvestManUrlThread(threading.Thread):
    """ Class to download a url in a separate thread """

    # The last error which caused a thread instance to die
    _lasterror = None
    
    def __init__(self, name, timeout, threadpool):
        """ Constructor, the constructor takes a url, a filename
        , a timeout value, and the thread pool object pooling this
        thread """

        # url Object (This is an instance of urlPathParser class)
        self._urlobject = None
        # thread queue object pooling this thread
        self._pool = threadpool
        # max lifetime for the thread
        self._timeout = timeout
        # start time of thread
        self._starttime = 0
        # start time of a download
        self._dstartime = 0
        # sleep time
        self._sleepTime = 1.0
        # error dictionary
        self._error = {}
        # download status 
        self._downloadstatus = 0
        # busy flag
        self._busyflag = False
        # end flag
        self._endflag = False
        # Url data, only used for mode 1
        self._data = ''
        # Url temp file, used for mode 0
        self._urltmpfile = ''
        # Current connector
        self._conn = None
        # initialize threading
        threading.Thread.__init__(self, None, None, name)
        
    def get_error(self):
        """ Get error value of this thread """

        return self._error

    def get_status(self):
        """ Get the download status of this thread """

        return self._downloadstatus

    def get_data(self):
        """ Return the data of this thread """

        return self._data

    def get_tmpfname(self):
        """ Return the temp filename if any """

        return self._urltmpfile

    def set_tmpfname(self, filename):
        """ Set the temporary filename """

        # Typically called by connector objects
        self._urltmpfile = filename
        
    def set_status(self, status):
        """ Set the download status of this thread """

        self._downloadstatus = status

    def is_busy(self):
        """ Get busy status for this thread """

        return self._busyflag

    def set_busy_flag(self, flag):
        """ Set busy status for this thread """

        self._busyflag = flag

    def join(self):
        """ The thread's join method to be called
        by other threads """

        threading.Thread.join(self, self._timeout)

    def terminate(self):
        """ Kill this thread """

        self.stop()
        msg = 'Download thread, ' + self.getName() + ' killed!'
        raise HarvestManUrlThreadInterrupt, msg

    def stop(self):
        """ Stop this thread """

        # If download was not completed, push-back object
        # to the pool.
        if self._downloadstatus==0 and self._urlobject:
            self._pool.push(self._urlobject)
            
        self._endflag = True

    def download(self, url_obj):
        """ Download this url """

        # Set download status
        self._downloadstatus = 0
        self._dstartime = time.time()
        
        url = url_obj.get_full_url()

        if not url_obj.trymultipart:
            if url_obj.is_image():
                moreinfo('Downloading image ...', url)
            else:
                moreinfo('Downloading url ...', url)
        else:
            startrange = url_obj.range[0]
            endrange = url_obj.range[-1]
            moreinfo('%s: Downloading url %s, byte range(%d - %d)' % (str(self),url,startrange,endrange))

        conn_factory = GetObject('connectorfactory')
        # This call will block if we exceed the number of connections
        # moreinfo("Creating connector for url ", urlobj.get_full_url())
        self._conn = conn_factory.create_connector( url_obj )
        self._conn.set_data_mode(self._pool.get_data_mode())
        mode = self._conn.get_data_mode()
        
        if not url_obj.trymultipart:
            res = self._conn.save_url(url_obj)
        else:
            res = self._conn.wrapper_connect(url_obj)
            # print 'Connector returned',self,url_obj.get_full_url()
            # This has a different return value.
            # 0 indicates data was downloaded fine.
            if res==0: res=1
            
            if mode == 0:
                self._urltmpfile = self._conn.get_tmpfname()
            elif mode == 1:
                self._data = self._conn.get_data()

        # Remove the connector from the factory
        conn_factory.remove_connector(self._conn)
        
        # Set this as download status
        self._downloadstatus = res
        
        # get error flag from connector
        self._error = self._conn.get_error()

        self._conn = None
        
        # Notify thread pool
        self._pool.notify(self)

        if res != 0:
            if not url_obj.trymultipart:            
                extrainfo('Finished download of ', url)
            else:
                startrange = url_obj.range[0]
                endrange = url_obj.range[-1]                            
                extrainfo('Finished download of byte range(%d - %d) of %s' % (startrange,endrange, url))
        else:
            extrainfo('Failed to download URL',url)

    def run(self):
        """ Run this thread """

        while not self._endflag:
            try:
                if os.name=='nt' or sys.platform == 'win32':
                  self._starttime=time.clock()
                else:
                    self._starttime=time.time()

                url_obj = self._pool.get_next_urltask()

                if self._pool.check_duplicates(url_obj):
                    continue

                if not url_obj:
                    time.sleep(0.1)
                    continue

                # set busy flag to 1
                self._busyflag = True

                # Save reference
                self._urlobject = url_obj

                filename, url = url_obj.get_full_filename(), url_obj.get_full_url()
                if not filename and not url:
                    return

                # Perf fix: Check end flag
                # in case the program was terminated
                # between start of loop and now!
                if not self._endflag: self.download(url_obj)
                # reset busyflag
                # print 'Setting busyflag to False',self
                self._busyflag = False
            except Exception, e:
                # raise
                debug('Worker thread Exception',e)
                # Now I am dead - so I need to tell the pool
                # object to migrate my data and produce a new thread.
                
                # See class for last error. If it is same as
                # this error, don't do anything since this could
                # be a programming error and will send us into
                # a loop...

                # Set busyflag to False
                self._busyflag = False
                # Remove the connector from the factory
                
                if self._conn and (not self._conn.is_released()):
                    conn_factory = GetObject('connectorfactory')
                    conn_factory.remove_connector(self._conn)
                
                if str(self.__class__._lasterror) == str(e):
                    debug('Looks like a repeating error, not trying to restart worker thread %s' % (str(self)))
                else:
                    self.__class__._lasterror = e
                    # self._pool.dead_thread_callback(self)
                    extrainfo('Worker thread %s has died due to error: %s' % (str(self), str(e)))
                    extrainfo('Worker thread was downloading URL %s' % url_obj.get_full_url())

    def get_url(self):

        if self._urlobject:
            return self._urlobject.get_full_url()

        return ""

    def get_filename(self):

        if self._urlobject:
            return self._urlobject.get_full_filename()

        return ""

    def get_urlobject(self):
        """ Return this thread's url object """

        return self._urlobject

    def get_connector(self):
        """ Return the connector object """

        return self._conn
    
    def set_urlobject(self, urlobject):
            
        self._urlobject = urlobject
        
    def get_start_time(self):
        """ Return the start time of current download """

        return self._starttime

    def set_start_time(self, starttime):
        """ Return the start time of current download """

        self._starttime = starttime
    
    def get_elapsed_time(self):
        """ Get the time taken for this thread """

        now=0.0

        if os.name=='nt' or sys.platform=='win32':
            now=time.clock()
        else:
            now=time.time()

        fetchtime=float(math.ceil((now-self._starttime)*100)/100)
        return fetchtime

    def get_elapsed_download_time(self):
        """ Return elapsed download time for this thread """

        fetchtime=float(math.ceil((time.time()-self._dstartime)*100)/100)
        return fetchtime
        
    def long_running(self):
        """ Find out if this thread is running for a long time
        (more than given timeout) """

        # if any thread is running for more than <timeout>
        # time, return TRUE
        return (self.get_elapsed_time() > self._timeout)

    def set_timeout(self, value):
        """ Set the timeout value for this thread """

        self._timeout = value

    def close_file(self):
        """ Close temporary file objects of the connector """

        # Currently used only by hget
        if self._conn:
            reader = self._conn.get_reader()
            if reader: reader.close()
        
class HarvestManUrlThreadPool(Queue):
    """ Thread group/pool class to manage download threads """

    def __init__(self):
        """ Initialize this class """

        # list of spawned threads
        self._threads = []
        # list of url tasks
        self._tasks = []
        self._cfg = GetObject('config')
        # Maximum number of threads spawned
        self._numthreads = self._cfg.threadpoolsize
        self._timeout = self._cfg.timeout
        
        # Last thread report time
        self._ltrt = 0.0
        # Local buffer
        self.buffer = []
        # Data dictionary for multi-part downloads
        # Keys are URLs and value is the data
        self._multipartdata = {}
        # Status of URLs being downloaded in
        # multipart. Keys are URLs
        self._multipartstatus = {}
        # Number of parts
        self._parts = self._cfg.numparts
        # Data mode
        # 0 => Flush data
        # 1 => keep data in memory (default)
        # This mode is perpetuated to connector objects
        # and reader objects belonging to connectors. It
        # is not an attribute of this class
        self._datamode = 1
        if self._cfg.flushdata: self._datamode = 0
        # Condition object
        self._cond = threading.Condition(threading.Lock())        
        Queue.__init__(self, self._numthreads + 5)
        
    def get_state(self):
        """ Return a snapshot of the current state of this
        object and its containing threads for serializing """
        
        d = {}
        d['buffer'] = self.buffer
        d['queue'] = self.queue
        
        tdict = {}
        
        for t in self._threads:
            d2 = {}
            d2['_urlobject'] = t.get_urlobject()
            d2['_busyflag'] = t.is_busy()
            d2['_downloadstatus'] = t.get_status()
            d2['_starttime'] = t.get_start_time()

            tdict[t.getName()]  = d2

        d['threadinfo'] = tdict
        
        return copy.deepcopy(d)

    def set_state(self, state):
        """ Set state to a previous saved state """

        # Maximum number of threads spawned
        self._numthreads = self._cfg.threadpoolsize
        self._timeout = self._cfg.timeout
        self._parts = self._cfg.numparts
        
        self.buffer = state.get('buffer',[])
        self.queue = state.get('queue', deque([]))
        
        for name,tdict in state.get('threadinfo').items():
            fetcher = HarvestManUrlThread(name, self._timeout, self)
            fetcher.set_urlobject(tdict.get('_urlobject'))
            fetcher.set_busy_flag(tdict.get('_busyflag', False))
            fetcher.set_status(tdict.get('_downloadstatus', 0))
            fetcher.set_start_time(tdict.get('_starttime', 0))            
            
            fetcher.setDaemon(True)
            self._threads.append(fetcher)
            
    def start_threads(self):
        """ Start threads if they are not running """

        for t in self._threads:
            try:
                t.start()
            except AssertionError, e:
                pass
            
    def spawn_threads(self):
        """ Start the download threads """

        for x in range(self._numthreads):
            name = 'Worker-'+ str(x+1)
            fetcher = HarvestManUrlThread(name, self._timeout, self)
            fetcher.setDaemon(True)
            # Append this thread to the list of threads
            self._threads.append(fetcher)
            debug('Starting thread',fetcher)
            fetcher.start()

    def download_urls(self, listofurlobjects):
        """ Method to download a list of urls.
        Each member is an instance of a urlPathParser class """

        for urlinfo in listofurlobjects:
            self.push(urlinfo)

    def _get_num_blocked_threads(self):

        blocked = 0
        for t in self._threads:
            if not t.is_busy(): blocked += 1

        return blocked

    def is_blocked(self):
        """ The queue is considered blocked if all threads
        are waiting for data, and no data is coming """

        blocked = self._get_num_blocked_threads()

        if blocked == len(self._threads):
            return True
        else:
            return False

    def push(self, urlObj):
        """ Push the url object and start downloading the url """

        # unpack the tuple
        try:
            filename, url = urlObj.get_full_filename(), urlObj.get_full_url()
        except:
            return

        # Wait till we have a thread slot free, and push the
        # current url's info when we get one
        try:
            self.put( urlObj )
            # If this URL was multipart, mark it as such
            self._multipartstatus[url] = False
            debug("Pushed URL to queue", urlObj.get_full_url())            
        except Full:
            debug("Thread queue full, appending to buffer", urlObj.get_full_url())
            self.buffer.append(urlObj)
        
    def get_next_urltask(self):

        # Insert a random sleep in range
        # of 0 - 0.5 seconds
        # time.sleep(random.random()*0.5)

        caller = threading.currentThread()
        try:
            if len(self.buffer):
                # Get last item from buffer
                item = buffer.pop()
                return item
            else:
                item = self.get()
                return item
            
        except Empty:
            return None

    def notify(self, thread):
        """ Method called by threads to notify that they
        have finished """

        try:
            self._cond.acquire()

            # Mark the time stamp (last thread report time)
            self._ltrt = time.time()

            urlObj = thread.get_urlobject()

            # See if this was a multi-part download
            if urlObj.trymultipart:
                # print 'Thread %s reported with data range (%d-%d)!' % (thread, urlObj.range[0], urlObj.range[-1])
                if thread.get_status()==1:
                    # print 'Thread %s reported %s' % (thread, urlObj.get_full_url())
                    # For flush mode, get the filename
                    # for memory mode, get the data
                    flushmode = self._cfg.flushdata

                    fname, data = '',''
                    if flushmode:
                        fname = thread.get_tmpfname()
                    else:
                        data = thread.get_data()

                    index = urlObj.index

                    if index in self._multipartdata:
                        infolist = self._multipartdata[index]
                        if data:
                            infolist.append((urlObj.range[0],data))
                        elif fname:
                            infolist.append((urlObj.range[0],fname))                        
                    else:
                        infolist = []
                        if data:
                            infolist.append((urlObj.range[0],data))
                        elif fname:
                            infolist.append((urlObj.range[0],fname))
                        #else:
                        #    self._parts -= 1 # AD-HOC

                        self._multipartdata[index] = infolist

                    # print 'Length of data list is',len(infolist)
                    if len(infolist)==self._parts:
                        # Sort the data list  according to byte-range
                        infolist.sort()
                        # Download of this URL is complete...
                        logconsole('Download of %s is complete...' % urlObj.get_full_url())
                        if not flushmode:
                            data = ''.join([item[1] for item in infolist])
                            self._multipartdata['data:' + str(index)] = data
                        else:
                            pass

                        self._multipartstatus[index] = True

            # if the thread failed, update failure stats on the data manager
            dmgr = GetObject('datamanager')

            err = thread.get_error()

            tstatus = thread.get_status()

            # Either file was fetched or file was uptodate
            if err.get('number',0) in (0, 304):
                # thread succeeded, increment file count stats on the data manager
                dmgr.update_file_stats( urlObj, tstatus)
            else:
                dmgr.update_failed_files( urlObj )

        finally:
            self._cond.release()

    def has_busy_threads(self):
        """ Return whether I have any busy threads """

        val=0
        for thread in self._threads:
            if thread.is_busy():
                val += 1
                break
            
        return val

    def get_busy_threads(self):
        """ Return a list of busy threads """

        return [thread for thread in self._threads if thread.is_busy()]

    def get_busy_count(self):
        """ Return a count of busy threads """

        return len(self.get_busy_threads())

    def locate_thread(self, url):
        """ Find a thread which downloaded a certain url """

        for x in self._threads:
            if not x.is_busy():
                if x.get_url() == url:
                    return x

        return None

    def locate_busy_threads(self, url):
        """ Find all threads which are downloading a certain url """

        threads=[]
        for x in self._threads:
            if x.is_busy():
                if x.get_url() == url:
                    threads.append(x)

        return threads

    def check_duplicates(self, urlobj):
        """ Avoid downloading same url file twice.
        It can happen that same url is linked from
        different web pages. We query any thread which
        has downloaded this url, and copy the file to
        the file location of the new download request """

        filename = urlobj.get_full_filename()
        url = urlobj.get_full_url()

        # First check if any thread is in the process
        # of downloading this url.
        if self.locate_thread(url):
            extrainfo('Another thread is downloading %s' % url)
            return True
        
        # Get data manager object
        dmgr = GetObject('datamanager')

        if dmgr.is_file_downloaded(filename):
            return True

        return False

    def end_hanging_threads(self):
        """ If any download thread is running for too long,
        kill it, and remove it from the thread pool """

        pool=[]
        for thread in self._threads:
            if thread.long_running(): pool.append(thread)

        for thread in pool:
            extrainfo('Killing hanging thread ', thread)
            # remove this thread from the thread list
            self._threads.remove(thread)
            # kill it
            try:
                thread.terminate()
            except HarvestManUrlThreadInterrupt:
                pass

            del thread

    def end_all_threads(self):
        """ Kill all running threads """

        try:
            self._cond.acquire()
            for t in self._threads:
                try:
                    t.terminate()
                    del t
                except HarvestManUrlThreadInterrupt, e:
                    extrainfo(str(e))
                    pass

            self._threads = []
        finally:
            self._cond.release()

    def remove_finished_threads(self):
        """ Clean up all threads that have completed """

        for thread in self._threads:
            if not thread.is_busy():
                self._threads.remove(thread)
                del thread

    def last_thread_report_time(self):
        """ Return the last thread reported time """

        return self._ltrt

    def get_multipart_download_status(self, url):
        """ Get status of multipart downloads """

        return self._multipartstatus.get(url.index, False)

    def get_multipart_url_data(self, url):
        """ Return data for multipart downloads """

        return self._multipartdata.get('data:'+ str(url.index), '')

    def get_multipart_url_info(self, url):
        """ Return information for multipart downloads """

        return self._multipartdata.get(url.index, '')

    def get_data_mode(self):
        """ Return the data mode """

        return self._datamode

    def dead_thread_callback(self, t):
        """ Call back function called by a thread if it
        dies with an exception. This class then creates
        a fresh thread, migrates the data of the dead
        thread to it """

        try:
            self._cond.acquire()
            new_t = HarvestManUrlThread(t.getName(), self._timeout, self)
            # Migrate data and start thread
            if new_t:
                new_t.set_urlobject(t.get_urlobject())
                # Replace dead thread in the list
                idx = self._threads.index(t)
                self._threads[idx] = new_t
                new_t.start()
            else:
                # Could not make new thread, remove
                # current thread anyway
                self._threads.remove(t)
        finally:
            self._cond.release()                
                    
    def get_threads(self):
        """ Return the list of thread objects """

        return self._threads

    def get_thread_urls(self):
        """ Return a list of current URLs being downloaded """

        # This returns a list of URL objects, not URL strings
        urlobjs = []

        for t in self._threads:
            if t.is_busy():
                urlobj = t.get_urlobject()
                if urlobj: urlobjs.append(urlobj)

        return urlobjs
