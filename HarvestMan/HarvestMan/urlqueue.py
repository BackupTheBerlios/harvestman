# -- coding: latin-1
""" urlqueue.py - Module which controls queueing of urls
created by crawler threads. This is part of the HarvestMan
program.

Modification History

Anand Jan 12 2005 - Created this module, by splitting urltracker.py

"""

import bisect
import Queue
import crawler
import time
import threading
import sys, os

from common import *

class PriorityQueue(Queue.Queue):
    """ Priority queue based on bisect module (courtesy: Effbot) """

    def __init__(self, maxsize=0):
        Queue.Queue.__init__(self, maxsize)

    def _init(self, maxsize):
        self.maxsize = maxsize
        self.queue = MyDeque()
        
    def _put(self, item):
        bisect.insort(self.queue, item)

    def _qsize(self):
        return len(self.queue)

    def _empty(self):
        return not self.queue

    def _full(self):
        return self.maxsize>0 and len(self.queue) == self.maxsize

    def _get(self):
        return self.queue.pop(0)    
    
class HarvestManCrawlerQueue(object):
    """ This class functions as the thread safe queue
    for storing url data for tracker threads """

    def __init__(self):
        self._basetracker = None
        self._controller = None # New in 1.4
        self._flag = 0
        self._pushes = 0
        self._lockedinst = 0
        self._lasttimestamp = time.time()
        self._trackers  = []
        self._requests = 0
        self._trackerindex = 0
        self._lastblockedtime = 0
        self._numfetchers = 0
        self._numcrawlers = 0
        self.__qsize = 0
        self._baseUrlObj = None
        # Time to wait for a data operation on the queue
        # before stopping the project with a timeout.
        self._waittime = GetObject('config').projtimeout
        self._configobj = GetObject('config')
        self.url_q = PriorityQueue(4*self._configobj.maxtrackers)
        self.data_q = PriorityQueue(4*self._configobj.maxtrackers)
        # Local buffer - new in 1.4.5
        self.buffer = []
        
    def increment_lock_instance(self, val=1):
        self._lockedinst += val

    def get_locked_instances(self):
        return self._lockedinst

    def get_controller(self):
        """ Return the controller thread object """

        return self._controller
        
    def configure(self):
        """ Configure this class with this config object """

        try:
            import urlparser
            
            urlparser.HarvestManUrlParser.reset_IDX()
            
            self._baseUrlObj = urlparser.HarvestManUrlParser(self._configobj.url, 'normal',
                                                             0, self._configobj.url,
                                                             self._configobj.projdir)
            SetUrlObject(self._baseUrlObj)
        except urlparser.HarvestManUrlParserError:
            return False

        self._baseUrlObj.is_starting_url = True
        
        if self._configobj.fastmode:
            self._basetracker = crawler.HarvestManUrlFetcher( 0, self._baseUrlObj, True )
        else:
            self._basetracker = crawler.HarvestManUrlDownloader( 0, self._baseUrlObj, False )
            
        self._trackers.append(self._basetracker)
        return True

    def mainloop(self):
        """ The loop where this object spends
        most of its time. However it is not
        an idle loop """

        # New in 1.4.5, moving code from
        # the crawl method.
        count=0

        if self._configobj.nocrawl:
            numstops = 1
        else:
            numstops = 3
        
        while 1:
            time.sleep(1.0)
            
            if self.is_exit_condition():
                count += 1
                    
            if count==numstops:
                break

    def crawl(self):
        """ Starts crawling for this project """

        # Reset flag
        self._flag = 0
        
        if os.name=='nt':
            t1=time.clock()
        else:
            t1=time.time()

        # Set start time on config object
        self._configobj.starttime = t1

        if not self._configobj.urlserver:
            self.push(self._baseUrlObj, 'crawler')
        else:
            try:
                # Flush url server of any previous urls by
                # sending a flush command.
                send_url("flush", self._configobj.urlhost, self._configobj.urlport)
                send_url(str(self._baseUrlObj.index),
                         self._configobj.urlhost,
                         self._configobj.urlport)
            except:
                pass

        # Start harvestman controller thread
        # (New in 1.4)
        import datamgr
        
        self._controller = datamgr.harvestManController()
        self._controller.start()
            
        if self._configobj.fastmode:
            # Create the number of threads in the config file
            # Pre-launch the number of threads specified
            # in the config file.

            # Initialize thread dictionary
            self._basetracker.setDaemon(True)
            self._basetracker.start()

            # For simple downloads using nocrawl option
            # there is no need to start more than one
            # thread. The following one line is the core
            # of the nocrawl mode, apart from a few
            # changes in datamgr and config.
            if not self._configobj.nocrawl:
                while self._basetracker.get_status() != 0:
                    time.sleep(0.1)

                for x in range(1, self._configobj.maxtrackers):
                    
                    # Back to equality among threads
                    if x % 2==0:
                        t = crawler.HarvestManUrlFetcher(x, None)
                    else:
                        t = crawler.HarvestManUrlCrawler(x, None)
                    
                    self.add_tracker(t)
                    t.setDaemon(True)
                    t.start()

                for t in self._trackers:
                    
                    if t.get_role() == 'fetcher':
                        self._numfetchers += 1
                    elif t.get_role() == 'crawler':
                        self._numcrawlers += 1

                # bug: give the threads some time to start,
                # otherwise we exit immediately sometimes.
                time.sleep(2.0)

            self.mainloop()
            
            # Set flag to 1 to denote that downloading is finished.
            self._flag = 1
            
            self.stop_threads(noexit = True)
        else:
            self._basetracker.action()

    def get_base_tracker(self):
        """ Get the base tracker object """

        return self._basetracker

    def get_base_urlobject(self):

        return self._baseUrlObj
    
    def get_url_data(self, role):
        """ Pop url data from the queue """

        if self._flag: return None

        obj = None

        blk = self._configobj.blocking
        
        if role == 'crawler':
            try:
                if blk:
                    obj=self.data_q.get()
                else:
                    obj=self.data_q.get_nowait()
            except Queue.Empty:
                return None
                
        elif role == 'fetcher' or role=='tracker':
            try:
                if blk:
                    obj = self.url_q.get()
                else:
                    obj = self.url_q.get_nowait()
            except Queue.Empty:
                return None
            
        self._lasttimestamp = time.time()        

        self._requests += 1
        return obj

    def __get_num_blocked_threads(self):

        blocked = 0
        for t in self._trackers:
            if not t.has_work(): blocked += 1

        return blocked

    def get_num_alive_threads(self):

        live = 0
        for t in self._trackers:
            if t.isAlive(): live += 1

        return live
        
    def __get_num_locked_crawler_threads(self):

        locked = 0
        for t in self._trackers:
            if t.get_role() == 'crawler':
                if t.is_locked(): locked += 1

        return locked

    def __get_num_locked_fetcher_threads(self):
        
        locked = 0
        for t in self._trackers:
            if t.get_role() == 'fetcher':
                if t.is_locked(): locked += 1

        return locked
    
    def add_tracker(self, tracker):
        self._trackers.append( tracker )
        self._trackerindex += 1

    def remove_tracker(self, tracker):
        self._trackers.remove(tracker)
        
    def get_last_tracker_index(self):
        return self._trackerindex
    
    def print_busy_tracker_info(self):
        
        for t in self._trackers:
            if t.has_work():
                print t,' =>', t.getUrl()
            
    def is_locked_up(self, role):
         """ The queue is considered locked up if all threads
         are waiting to push data, but none can since queue
         is already full, and no thread is popping data. This
         is a deadlock condition as the program cannot go any
         forward without creating new threads that will pop out
         some of the data (We need to take care of it by spawning
         new threads which can pop data) """

         locked = 0
         
         if role == 'fetcher':
             locked = self.__get_num_locked_fetcher_threads()
             if locked == self._numfetchers - 1:
                 return True
         elif role == 'crawler':
             locked = self.__get_num_locked_crawler_threads()
             if locked == self._numcrawlers - 1:
                 return True             

         return False
     
    def is_exit_condition(self):
        """ Exit condition is when there are no download
        sub-threads running and all the tracker threads
        are blocked or if the project times out """

        dmgr = GetObject('datamanager')
            
        currtime = time.time()
        last_thread_time = dmgr.last_download_thread_report_time()

        if last_thread_time > self._lasttimestamp:
            self._lasttimestamp = last_thread_time
            
        timediff = currtime - self._lasttimestamp

        is_blocked = self.is_blocked()
        if is_blocked:
            self._lastblockedtime = time.time()
            
        has_running_threads = dmgr.has_download_threads()
        timed_out = False

        # If the trackers are blocked, but waiting for sub-threads
        # to finish, kill the sub-threads.
        if is_blocked and has_running_threads:
            # Find out time difference between when trackers
            # got blocked and curr time. If greater than 1 minute
            # Kill hanging threads
            timediff2 = currtime - self._lastblockedtime
            if timediff2 > 60.0:
                moreinfo("Killing download threads ...")
                dmgr.kill_download_threads()
            
        if is_blocked and not has_running_threads:
            return True
        
        if timediff > self._waittime:
            timed_out = True
        
        if timed_out:
            moreinfo("Project", self._configobj.project, "timed out.")
            moreinfo('(Time since last data operation was', timediff, 'seconds)')
            return True

        return False
        
    def is_blocked(self):
        """ The queue is considered blocked if all threads
        are waiting for data, and no data is coming """

        blocked = self.__get_num_blocked_threads()

        # print 'Blocked threads=>',blocked
        if blocked == len(self._trackers):
            return True
        else:
            return False

    def is_fetcher_queue_full(self):
        """ Check whether the fetcher queue is full """

        if self.__get_num_locked_fetcher_threads() == self._numfetchers - 1:
            return True
        
        return False

    def is_crawler_queue_full(self):
        """ Check whether the crawler queue is full """

        if self.__get_num_locked_crawler_threads() == self._numcrawlers - 1:
            return True
        
        return False        
        
    def push(self, obj, role):
        """ Push trackers to the queue """

        if self._flag: return

        # 1.4 alpha 3 - Big fix for hanging threads.
        # Instead of perpetually waiting at queues
        # (blocking put), the threads now do a mix
        # of unblocking put plus local buffers.

        # Each thread tries to put data to buffer
        # for maximum five attempts, each separated
        # by a 0.5 second gap.
        ntries, status = 0, 0

        if role == 'crawler' or role=='tracker' or role =='downloader':
            while ntries < 5:
                try:
                    ntries += 1
                    self.url_q.put_nowait((obj.get_priority(), obj.index))
                    status = 1
                    break
                except Queue.Full:
                    time.sleep(0.5)
                    
        elif role == 'fetcher':
            stuff = (obj[0].get_priority(), (obj[0].index, obj[1]))
            while ntries < 5:
                try:
                    ntries += 1
                    self.data_q.put_nowait(stuff)
                    status = 1
                    break
                except Queue.Full:
                    time.sleep(0.5)
                    
        self._pushes += 1
        self._lasttimestamp = time.time()

        return status
    
    def stop_threads(self, noexit=False):
        """ Stop all running threads and clean
        up the program. This function is called
        for a normal exit of HravestMan """

        if self._configobj.project:
            moreinfo("Ending Project", self._configobj.project,'...')
        for t in self._trackers:
            try:
                t.terminate()
                t.join()
            except crawler.HarvestManUrlCrawlerException, e:
                pass
            except Exception, e:
                pass

        # Stop controller
        self._controller.stop()

        # Reset the thread list
        self.empty_list()
        
        # Exit the system
        if not noexit:
            sys.exit(0)

    def terminate_threads(self):
        """ Kill all current running threads and
        stop the program. This function is called
        for an abnormal exit of HarvestMan """

        # Created: 23 Nov 2004
        # Kill the individual download threads
        mgr = GetObject('datamanager')
        mgr.kill_download_threads()

        # Stop controller thread
        self._controller.stop()
 
        # If not fastmode, then there are no
        # further threads!
        if not self._configobj.fastmode:
            self._basetracker.stop()
            return 

        # Kill tracker threads
        self.__kill_tracker_threads()
    
    def __kill_tracker_threads(self):
        """ This function kills running tracker threads """

        moreinfo('Terminating project ',self._configobj.project,'...')
        self._flag=1

        count =0

        debug('Waiting for threads to clean up ')

        for tracker in self._trackers:
            count += 1
            sys.stdout.write('...')

            if count % 10 == 0: sys.stdout.write('\n')

            try:
                tracker.terminate()
                tracker.join()
            except crawler.HarvestManUrlCrawlerException, e:
                pass
            except AssertionError, e:
                print str(e), '=> ', tracker
            except ValueError, e:
                print str(e), '=> ', tracker

            del tracker
            
        # Reset the thread list
        self.empty_list()
        
    def empty_list(self):
        """ Remove thread objects from the thread list """

        self._trackers = []
        self._basetracker = None

    def recycle_thread(self, tracker):
        """ Recycle and regenerate a tracker thread """

        # Not used in 1.4.5 - Need to look into
        # this as a part of thread checkpointing
        # in next version.
        
        # Get the type of thread
        role = tracker.get_role()
        # Get its url object and index
        urlobj, idx = tracker.get_url_object(), tracker.get_index()
        links = []
        
        # Kill the thread and remove it
        # from the list
        try:
            self._trackers.remove(tracker)
            tracker.terminate()
        except:
            pass

        # Create a new tracker
        if role == 'fetcher':
            new_thread = crawler.HarvestManUrlFetcher(idx, None, True)
        elif role == 'crawler':
            new_thread = crawler.HarvestManUrlCrawler(idx, None, True)            
            links = tracker.links
            
        self._trackers.append(new_thread)
        new_thread.start()

        if urlobj:
            if role=='fetcher':
                self.buffer.append(urlobj)
            elif role=='crawler':
                self.buffer.append((urlobj,links))
        else:
            pass
