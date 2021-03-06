# -- coding: latin-1
""" datamgr.py - Data manager module for HarvestMan.
    This module is part of the HarvestMan program.

    Author: Anand B Pillai <abpillai at gmail dot com>
    
    Oct 13 2006     Anand          Removed data lock since it is not required - Python GIL
                                   automatically locks byte operations.

    Feb 2 2007      Anand          Re-added function parse_style_sheet which went missing.

    Feb 26 2007      Anand          Fixed bug in check_duplicate_download for stylesheets.
                                   Also rewrote logic.

    Mar 05 2007     Anand          Added method get_last_modified_time_and_data to support
                                   server-side cache checking using HTTP 304. Fixed a small
                                   bug in css url handling.
                                   
   Copyright (C) 2004 Anand B Pillai.
    
"""

__version__ = '1.5 b1'
__author__ = 'Anand B Pillai'

import os, sys
import time
import math
import binascii
import re
import sha
import copy

import threading as tg
# Utils
import utils

from urlthread import HarvestManUrlThreadPool
from connector import *
from common.common import *
from common.methodwrapper import MethodWrapperMetaClass

# Defining pluggable functions
__plugins__ = { 'download_url_plugin': 'HarvestManDataManager:download_url',
                'post_download_setup_plugin': 'HarvestManDataManager:post_download_setup',
                'print_project_info_plugin': 'HarvestManDataManager:print_project_info',
                'dump_url_tree_plugin': 'HarvestManDataManager:dump_url_tree'}

# Defining functions with callbacks
__callbacks__ = { 'download_url_callback': 'HarvestManDataManager:download_url' }

class HarvestManDataManager(object):
    """ The data manager cum indexer class """

    # For supporting callbacks
    __metaclass__ = MethodWrapperMetaClass
    
    def __init__(self):

        self._numfailed = 0
        self._projectcache = {}
        self._downloaddict = { '_savedfiles': MyDeque(),
                               '_deletedfiles': MyDeque(),
                               '_failedurls' : MyDeque(),
                               '_doneurls': MyDeque(),
                               '_reposfiles' : 0,
                               '_cachefiles': 0
                             }
        # Config object
        self._cfg = GetObject('config')
        # Used for localizing links
        self._linksdict = {}
        # New datastructure added on Jan 10 06
        # to keep status of each fetcher
        self._fetcherstatus = {}
        # Dictionary of servers crawled and
        # their meta-data. Meta-data is
        # a dictionary which currently
        # has only one entry.
        # i.e accept-ranges.
        self._serversdict = {}
        # byte count
        self._bytes = 0L
        # Redownload flag
        self._redownload = False
        # Url thread group class for multithreaded downloads
        if self._cfg.usethreads and self._cfg.fastmode:
            self._urlThreadPool = HarvestManUrlThreadPool()
            self._urlThreadPool.spawn_threads()
        else:
            self._urlThreadPool = None

        # Regexp to parse stylesheet imports
        self._importcss1 = re.compile(r'(\@import\s+\"?)(?!url)([\w.-:/]+)(\"?)', re.MULTILINE|re.LOCALE|re.UNICODE)
        self._importcss2 = re.compile(r'(\@import\s+url\(\"?)([\w.-:/]+)(\"?\))', re.MULTILINE|re.LOCALE|re.UNICODE)
        # Regexp to parse URLs inside CSS files
        self._cssurl = re.compile(r'(url\()([^\)]+)(\))', re.LOCALE|re.UNICODE)
        
    def get_state(self):
        """ Return a snapshot of the current state of this
        object and its containing threads for serializing """
        
        d = {}
        d['_numfailed'] = self._numfailed
        d['_downloaddict'] = self._downloaddict.copy()
        d['_linksdict'] = self._linksdict.copy()
        d['_bytes'] = self._bytes

        return copy.deepcopy(d)

    def set_state(self, state):
        """ Set state to a previous saved state """
        
        self._numfailed = state.get('_numfailed', 0)
        self._downloaddict = state.get('_downloaddict', self._downloaddict)
        self._linksdict = state.get('_linksdict', {})
        self._bytes = state.get('_bytes', 0L)
        
    def get_proj_cache_filename(self):
        """ Return the cache filename for the current project """

        # Note that this function does not actually build the cache directory.
        # Get the cache file path
        if self._cfg.projdir and self._cfg.project:
            cachedir = os.path.join(self._cfg.projdir, "hm-cache")
            cachefilename = os.path.join(cachedir, self._cfg.project + ".hmc")

            return cachefilename
        else:
            return ''

    def get_proj_cache_directory(self):
        """ Return the cache directory for the current project """

        # Note that this function does not actually build the cache directory.
        # Get the cache file path
        if self._cfg.projdir and self._cfg.project:
            return os.path.join(self._cfg.projdir, "hm-cache")
        else:
            return ''        

    def get_links_dictionary(self):
        return self._linksdict

    def get_server_dictionary(self):
        return self._serversdict

    def supports_range_requests(self, urlobj):
        """ Check whether the given url object
        supports range requests """

        # Has 3 return values
        # 1 => accepts
        # 0 => do not know since it is not in
        # the server dictionary
        # -1 => does not accept
        
        # Look up its server in the dictionary
        server = urlobj.get_full_domain()
        if server in self._serversdict:
            d = self._serversdict[server]
            return d.get('accept-ranges', 0)

        return 0
        
    def parse_style_sheet(self, data):
        """ Parse stylesheet data and extract imported css links, if any """

        # Return is a list of imported css links.
        # This subroutine uses the specification mentioned at
        # http://www.w3.org/TR/REC-CSS2/cascade.html#at-import
        # for doing stylesheet imports.

        # This takes care of @import "style.css" and
        # @import url("style.css") and url(...) syntax.
        # Media types specified if any, are ignored.
        
        # Matches for @import "style.css"
        l1 = self._importcss1.findall(data)
        # Matches for @import url("style.css")
        l2 = self._importcss2.findall(data)
        # Matches for url(...)
        l3 = self._cssurl.findall(data)
        
        # The URL is the second item of the returned match tuple
        csslinks = []
        for item in (l1+l2+l3):
            if not item: continue
            url = item[1].replace("'",'').replace('"','')
            csslinks.append(url)

        return csslinks
    
    def read_project_cache(self):
        """ Try to read the project cache file """

        # Get cache filename
        moreinfo('Reading Project Cache...')
        cachereader = utils.HarvestManCacheManager(self.get_proj_cache_directory())
        obj = cachereader.read_project_cache()

        if obj:
            self._projectcache = obj
            self._cfg.cachefound = 1
        else:
            self._cfg.cachefound = 0

    def write_file_from_cache(self, urlobj):
        """ Write file from url cache. This
        works only if the cache dictionary of this
        url has a key named 'data' """

        ret = False
        
        d = self._projectcache.get(urlobj.get_full_domain(), {})

        url = urlobj.get_full_url()
        
        if d.has_key(url):
            # Value itself is a dictionary
            content = d[url]
            if content:
                fileloc = content['location']
                if not content.has_key('data'):
                    return ret
                else:
                    url_data = content['data']
                    if url_data:
                        # Write file
                        extrainfo("Updating file from cache=>", fileloc)
                        try:
                            f=open(fileloc, 'wb')
                            f.write(url_data)
                            f.close()
                            ret = True
                        except IOError, e:
                            debug('IO Exception', e)
                                
        return ret

    def wrapper_update_cache_for_url(self, urlobj, filename, contentlen, urldata):
        """ Wrapper for update_cache_for_url which is called from connector module """

        # Created this method - Anand Jan 10 06
        digest1 = ''
        if urldata:
            sh = sha.new()
            sh.update(urldata)
            digest1 = sh.hexdigest()
            
        return self.update_cache_for_url(urlobj, filename, contentlen, urldata, digest1)

    def wrapper_update_cache_for_url2(self, urlobj, filename, lmt, urldata):
        """ Wrapper for update_cache_for_url2 which is called from connector module """

        # Created this method - Anand Jan 10 06
        return self.update_cache_for_url2(urlobj, filename, lmt, urldata)
                                      
    def update_cache_for_url(self, urlobj, filename, contentlen, urldata, digeststr):
        """ Method to update the cache information for the URL 'url'
        associated to file 'filename' on the disk """

        url = urlobj.get_full_url()
        domain = urlobj.get_full_domain()
        
        # Jan 10 06 - Anand, Created by moving code from is_url_cache_uptodate
        # Update all cache keys
        cachekey = {}

        cachekey['checksum'] = bin_crypt(digeststr)
        cachekey['location'] = filename
        cachekey['content-length'] = contentlen
        cachekey['updated'] = True
        if self._cfg.datacache:
            cachekey['data'] = urldata

        d = self._projectcache.get(domain, {})
        d[url] = cachekey
        
        self._projectcache[domain] = d

    def update_cache_for_url2(self, urlobj, filename, lmt, urldata):
        """ Second method to update the cache information for the URL 'url'
        associated to file 'filename' on the disk """

        url = urlobj.get_full_url()
        domain = urlobj.get_full_domain()
        
        # Jan 10 06 - Anand, Created by moving code from is_url_uptodate.
        # Update all cache keys
        cachekey = {}

        cachekey['location'] = filename
        cachekey['last-modified'] = lmt
        cachekey['updated'] = True
        if self._cfg.datacache:
            cachekey['data'] = urldata            

        d = self._projectcache.get(domain, {})
        d[url] = cachekey
        
        self._projectcache[domain] = d                

    def get_last_modified_time_and_data(self, urlobj, check_file_exists=True):
        """ Return last-modified-time and data of the given URL if it
        was found in the cache """

        # return -1, ''
    
        # This is returned as Unix time, i.e number of
        # seconds since Epoch.

        # This will be called from connector to avoid downloading
        # URL data using HTTP 304. However, we support this only
        # if we have data for the URL.
        if (not self._cfg.pagecache) or (not self._cfg.datacache):
            return (-1, '')

        # Reference to dictionary in the cache list
        d = self._projectcache.get(urlobj.get_full_domain(), {})
        # Cache dictionary is indexed by domain names
        url = urlobj.get_full_url()

        if url in d:
            cachekey = d[url]
            
            # File check is enabled - return True only if
            # downloaded file is found.
            if check_file_exists:
                fileloc = cachekey['location']
                if os.path.exists(fileloc):
                    filename = urlobj.get_full_filename()
                    if os.path.abspath(fileloc) == os.path.abspath(filename):
                        # Check if we have the data for the URL
                        data = cachekey.get('data','')
                        if len(data):
                            return (cachekey.get('last-modified', -1), data)
                        else:
                            return (-1, '')

            else:
                # Get the data
                data = cachekey.get('data','')
                return (cachekey.get('last-modified', -1), data)

        return (-1, '')
                               
    def is_url_cache_uptodate(self, urlobj, filename, contentlen, urldata):
        """ Check with project cache and find out if the
        content needs update """
        
        # Sep 16 2003, fixed a bug in this, we need to check
        # the file existence also.

        # If page caching is not enabled, return False
        # straightaway!
        if not self._cfg.pagecache:
            return (False, False)

        # Return True if cache is uptodate(no update needed)
        # and Fals if cache is out-of-date(update needed)
        # NOTE: We are using an comparison of the sha checksum of
        # the file's data with the sha checksum of the cache file.
        if contentlen==0:
            return (False, False)

        # Anand 10/1/06 - Fix: need to update sha object with data to
        # get digest! (This line somehow has got deleted)
        digest1 = ''
        if urldata:
            sh = sha.new()
            sh.update(urldata)
            digest1 = sh.hexdigest()
        
        # Assume that cache is not uptodate apriori
        uptodate=False
        fileverified=False

        # Reference to dictionary in the cache list
        domain = urlobj.get_full_domain()        
        cachekey = {}
        
        d = self._projectcache.get(domain, {})

        url = urlobj.get_full_url()
        
        if d.has_key(url):
            cachekey = d[url]
            cachekey['updated']=False

            fileloc = cachekey['location']
            if os.path.exists(fileloc) and os.path.abspath(fileloc) == os.path.abspath(filename):
                fileverified=True
            
            if cachekey.has_key('checksum'):
                # This value is stored hex encrypted in the cache file
                # (and hence the dictionary). In order to compare, we need
                # to decrypt it, (or we need to compare it with the encrypted
                # copy of the file digest, as we are doing now).
                
                cachesha = bin_decrypt(cachekey['checksum'])
                if binascii.hexlify(cachesha) == binascii.hexlify(digest1) and fileverified:
                    uptodate=True

        if not uptodate:
            # Modified this logic - Anand Jan 10 06            
            self.update_cache_for_url(urlobj, filename, contentlen, urldata, digest1)

        return (uptodate, fileverified)

    def is_url_uptodate(self, urlobj, filename, lmt, urldata):
        """ New function to check whether the url cache is out
        of date by comparing last modified time """

        # If page caching is not enabled, return False
        # straightaway!
        if not self._cfg.pagecache:
            return (False, False)

        # Assume that cache is not uptodate apriori
        uptodate=False
        fileverified=False

        # Reference to dictionary in the cache list
        domain = urlobj.get_full_domain()                
        cachekey = {}

        d = self._projectcache.get(domain, {})
        # Cache dictionary is indexed by domain names
        url = urlobj.get_full_url()
        
        if d.has_key(url):
            cachekey = d[url]

            cachekey['updated']=False

            fileloc = cachekey['location']
            if os.path.exists(fileloc) and os.path.abspath(fileloc) == os.path.abspath(filename):
                fileverified=True

            if cachekey.has_key('last-modified'):
                # Get current modified time
                cmt = cachekey['last-modified']
                # If the latest page has a modified time greater than this
                # page is out of date, otherwise it is uptodate
                if lmt<=cmt:
                    uptodate=True

        # If cache is not updated, update all cache keys
        if not uptodate:
            # Modified this logic - Anand Jan 10 06                        
            self.update_cache_for_url2(urlobj, filename, lmt, urldata)

        return (uptodate, fileverified)

    def conditional_cache_set(self):
        """ A utility function to conditionally enable/disable
        the cache mechanism """

        # If the cache file exists for this project, disable
        # cache, else enable it.
        cachefilename = self.get_proj_cache_filename()

        if os.path.exists(cachefilename) and os.path.getsize(cachefilename):
            self._cfg.pagecache = False
        else:
            self._cfg.pagecache = True

    def does_cache_need_update(self):
        """ Find out if project cache needs update """

        # Fix: if no cache found, always return True
        if not self._cfg.cachefound: return True
        
        # If any of the dictionary entries has the key
        # value for 'updated' set to True, the cache needs
        # update, else not.
        needsupdate=False
        for urldict in self._projectcache.values():
            for cachekey in urldict.values():
                if cachekey.has_key('updated'):
                    if cachekey['updated']:
                        needsupdate=cachekey['updated']
                        return needsupdate

        return needsupdate

    def post_download_setup(self):
        """ Actions to perform after project is complete """

        if self._cfg.retryfailed:
            self._numfailed = len(self._downloaddict['_failedurls'])
            moreinfo(' ')
            # try downloading again
            # mod: made this multithreaded
            if self._numfailed:
                moreinfo('Redownloading failed links...',)
                self._redownload=True

                for urlobj in self._downloaddict['_failedurls']:
                    if not urlobj.fatal:
                        # Get calling thread
                        t = tg.currentThread()
                        self.download_url(t, urlobj )

        # bugfix: Moved the time calculation code here.
        if sys.platform == 'win32' or os.name=='nt':
            t2=time.clock()
        else:
            t2=time.time()

        self._cfg.endtime = t2

        # If url header dump is enabled,
        # dump it
        if self._cfg.urlheaders:
            self.add_headers_to_cache()

        # Write cache file
        if self._cfg.pagecache and self.does_cache_need_update():
            cachewriter = utils.HarvestManCacheManager( self.get_proj_cache_directory() )
            cachewriter.write_project_cache(self._projectcache, self._cfg.cachefileformat)

        # localise downloaded file's links, dont do if jit localisation
        # is enabled.
        if self._cfg.localise:
            self.localise_links()

        # Write archive file...
        if self._cfg.archive:
            self.archive_project()
            
        #  Get handle to rules checker object
        ruleschecker = GetObject('ruleschecker')
        # dump downloaded urls to a text file
        if self._cfg.urllistfile:
            # Get urls list file
            ruleschecker.dump_urls(self._cfg.urllistfile)
        # dump url tree (dependency tree) to a file
        if self._cfg.urltreefile:
            self.dump_urltree(self._cfg.urltreefile)

        if not self._cfg.project: return

        # print stats of the project

        nlinks, nservers, ndirs = ruleschecker.get_stats()
        nfailed = self._numfailed

        numstillfailed = len(self._downloaddict['_failedurls'])
        numfiles = len(self._downloaddict['_savedfiles'])
        numfilesinrepos = self._downloaddict['_reposfiles']
        numfilesincache = self._downloaddict['_cachefiles']

        numretried = self._numfailed  - numstillfailed
        fetchtime = float((math.modf((self._cfg.endtime-self._cfg.starttime)*100.0)[1])/100.0)

        statsd = { 'links' : nlinks,
                   'extservers' : nservers,
                   'extdirs' : ndirs,
                   'failed' : nfailed,
                   'fatal' : numstillfailed,
                   'files' : numfiles,
                   'filesinrepos' : numfilesinrepos,
                   'filesincache' : numfilesincache,
                   'retries' : numretried,
                   'fetchtime' : fetchtime,
                }

        self.print_project_info(statsd)

    def update_bytes(self, count):
        """ Update the global byte count """

        self._bytes += count


    def update_failed_files(self, urlObject):
        """ Add the passed information to the failed files list """

        if self._redownload: return -1

        try:
            self._downloaddict['_failedurls'].index(urlObject)
        except:
            self._downloaddict['_failedurls'].append(urlObject)

        return 0

    def remove_file_from_stats(self, filename, typ=0):
        """ Removed passed file from stats data structures """

        # typ mapping
        # 0 => saved files
        if typ==0:
            lookuplist = self._downloaddict['_savedfiles']
            if filename in lookuplist:
                lookuplist.remove(filename)
                return True

        return False
        
    def update_file_stats(self, urlObject, status):
        """ Add the passed information to the saved file list """

        if not urlObject: return -1

        # Bug: we should be getting this url as rooturl and not
        # the base url of this url.
        filename = urlObject.get_full_filename()

        ok=False

        # Status == 1 or 2 means look up in "_savedfiles"
        # Status == 3 means look up in "_reposfiles"
        # Status == 4 means look up in "_cachefiles"
        if status == 1 or status == 2:
            lookuplist = self._downloaddict['_savedfiles']
            if not filename in lookuplist:
                lookuplist.append( filename )
        elif status == 3:
            self._downloaddict['_reposfiles'] += 1
            extrainfo('Filename=>',filename,self._downloaddict['_reposfiles'])
        elif status == 4:
            self._downloaddict['_cachefiles'] += 1            
        else:
            return -1
        
        # If this was present in failed urls list, remove it
        try:
            self._downloaddict['_failedurls'].index(urlObject)
            self._downloaddict['_failedurls'].remove(urlObject)
        except:
            pass
            
        return 0
    
    def update_links(self, filename, urlobjlist):
        """ Update the links dictionary for this html file """

        if self._linksdict.has_key(filename):
            links = self._linksdict[filename]
            links.extend(urlobjlist)
        else:
            self._linksdict[filename] = urlobjlist

    def thread_download(self, urlObj):
        """ Download this url object in a separate thread """

        # Add this task to the url thread pool
        if self._urlThreadPool:
            self._urlThreadPool.push( urlObj )

    def has_download_threads(self):
        """ Return true if there are any download sub-threads
        running, else return false """

        if self._urlThreadPool:
            num_threads = self._urlThreadPool.has_busy_threads()
            if num_threads:
                return True

        return False

    def last_download_thread_report_time(self):
        """ Get the time stamp of the last completed
        download (sub) thread """

        if self._urlThreadPool:
            return self._urlThreadPool.last_thread_report_time()
        else:
            return 0

    def kill_download_threads(self):
        """ Terminate all the download threads """

        if self._urlThreadPool:
            self._urlThreadPool.end_all_threads()

    def create_local_directory(self, directory):
        """ Create the directories on the disk named 'directory' """

        # new in 1.4.5 b1 - No need to create the
        # directory for raw saves using the nocrawl
        # option.
        if self._cfg.rawsave:
            return 0
        
        try:
            if not os.path.exists( directory ):
                os.makedirs( directory )
                extrainfo("Created => ", directory)
            return 0
        except OSError:
            moreinfo("Error in creating directory", directory)
            return -1

        return 0

    def download_multipart_url(self, urlobj, clength):
        """ Download a URL using HTTP/1.1 multipart download
        using range headers """

        # First add entry of this domain in
        # dictionary, if not there
        domain = urlobj.get_full_domain()
        try:
            self._serversdict[domain]
        except KeyError:
            self._serversdict[domain] = {'accept-ranges': True}
            
        parts = self._cfg.numparts
        # Calculate size of each piece
        piecesz = clength/parts
        
        # Calculate size of each piece
        pcsizes = [piecesz]*parts
        # For last URL add the reminder
        pcsizes[-1] += clength % parts 
        # Set part-length size
        urlobj.__class__.partlengths = [0]*parts
        # Create a URL object for each and set range
        urlobjects = []
        for x in range(parts):
            urlobjects.append(copy.deepcopy(urlobj))

        prev = 0
        for x in range(parts):
            curr = pcsizes[x]
            next = curr + prev
            urlobject = urlobjects[x]
            urlobject.trymultipart = True
            urlobject.clength = clength
            urlobject.range = xrange(prev, next)
            urlobject.mindex = x
            prev = next
            self._urlThreadPool.push(urlobject)

        # Push this URL objects to the pool
        return 0

    def download_url(self, caller, urlobj):

        # Modified: Add all urlobjects to a local list
        # to avoid duplicate downloads. This is the best
        # way rather than checking downloads in progress.
        
        url = urlobj.get_full_url()
        
        try:
            self._downloaddict['_doneurls'].index(url)
        except ValueError:
            self._downloaddict['_doneurls'].append(url)            
        
        # Modified - Anand Jan 10 06, added the caller thread
        # argument to this function for keeping a dictionary
        # containing URLs currently being downloaded by fetchers.
        
        no_threads = (not self._cfg.usethreads) or \
                     urlobj.is_webpage() or \
                     urlobj.is_stylesheet()

        data=""
        if no_threads:
            # Update a local dictionary on the URLs
            # each fetcher is in charge of
            # Get the calling thread
            self._fetcherstatus[caller] = urlobj.get_full_url()
            server = urlobj.get_domain()
            conn_factory = GetObject('connectorfactory')

            # This call will block if we exceed the number of connections
            conn = conn_factory.create_connector( server )
            res = conn.save_url( urlobj )

            conn_factory.remove_connector(server)

            # Return values for res
            # 0 => error, file not downloaded
            # 1 => file downloaded ok
            # 2 => file downloaded with filename modification
            # 3 => file was not downloaded because cache was uptodate
            # 4 => file was copied from cache, since cache was uptodate
            # but file was deleted.
            # 5 => Some rules related to file content/mime-type
            # prevented file download.
            filename = urlobj.get_full_filename()
            if res:
                if res==2:
                    # There was a filename modification, so get the new filename
                    filename = GetObject('modfilename')
                else:
                    filename = urlobj.get_full_filename()

                if res==1:
                    moreinfo("Saved to",filename)

                self.update_file_stats( urlobj, res )

                data = conn.get_data()
            else:
                fetchurl = urlobj.get_full_url()
                extrainfo( "Failed to download url", fetchurl)
                self.update_failed_files(urlobj)

            del conn
        else:
            self.thread_download( urlobj )

        return data

    def is_file_downloaded(self, filename):
        """ Find if the <filename> is present in the
        saved files list """

        try:
            self._downloaddict['_savedfiles'].index(filename)
            return True
        except ValueError:
            return False

    def is_downloaded(self, url):
        """ Check whether the given URL was processed by
        download_url method """

        try:
            self._downloaddict['_doneurls'].index(url)
            return True
        except ValueError:
            return False
    
    def check_duplicates(self, url):
        """ Check for fetchers in charge of URL url.
        Return True if found, False otherwise """

        return url in self._fetcherstatus.values()
        
    def check_duplicate_download(self, urlobj):
        """ Check if this is a duplicate download """

        # Modified - Anand Jan 10 06
        # Modified to check fetcher status dictionary to avoid
        # duplicate downloads, also urlthredpool should be queried
        # only for non-webpage URLs.
        if urlobj.is_webpage() or urlobj.is_stylesheet():
            ret = self.is_file_downloaded(urlobj.get_full_filename())
            if ret:return ret
            # Check if some fetcher is already in charge
            # of this URL
            else:
                ret = self.check_duplicates(urlobj.get_full_url())
                if ret:
                    debug("Fetchers in charge of url",urlobj.get_full_url(),"...")
                return ret
        elif self._urlThreadPool:
            # Query worker thread pool, if enabled
            debug('Checking duplicates for url...',urlobj.get_full_url(),urlobj.get_type())
            return self._urlThreadPool.check_duplicates(urlobj)
        
    def clean_up(self):
        """ Purge data for a project by cleaning up
        lists, dictionaries and resetting other member items"""

        # Clean up project cache
        self._projectcache.clear()
        self._projectcache = {}
        self._downloaddict = {}
        # Clean up links dictionary
        self._linksdict.clear()
        # Reset byte count
        self._bytes = 0L

    def archive_project(self):
        """ Archive project files into a tar archive file.
        The archive will be further compressed in gz or bz2
        format. New in 1.4.5 """

        try:
            import tarfile
            extrainfo("Archiving project files...")
            # Get project directory
            projdir = self._cfg.projdir
            # Get archive format
            if self._cfg.archformat=='bzip':
                format='bz2'
            elif self._cfg.archformat=='gzip':
                format='gz'
            else:
                extrainfo("Archive Error: Archive format not recognized")
                return -1
            
            # Create tarfile name
            ptarf = os.path.join(self._cfg.basedir, "".join((self._cfg.project,'.tar.',format)))
            cwd = os.getcwd()
            os.chdir(self._cfg.basedir)
            
            # Create tarfile object
            tf = tarfile.open(ptarf,'w:'+format)
            # Projdir base name
            pbname = os.path.basename(projdir)
            
            # Add directories
            for item in os.listdir(projdir):
                # Skip cache directory, if any
                if item=='hm-cache':
                    continue
                # Add directory
                fullpath = os.path.join(projdir,item)
                if os.path.isdir(fullpath):
                    tf.add(os.path.join(pbname,item))
            # Dump the tarfile
            tf.close()
            
            os.chdir(cwd)            
            # Check whether writing was done
            if os.path.isfile(ptarf):
                extrainfo("Wrote archive file",ptarf)
                return 0
            else:
                extrainfo("Error in writing archive file",ptarf)
                return -1
            
        except ImportError, e:
            logconsole(e)
            return -1
        

    def add_headers_to_cache(self):
        """ Add original URL headers of urls downloaded
        as an entry to the cache file """

        links_dict = self.get_links_dictionary()
        for links in links_dict.values():
            for urlobj in links:
                if urlobj:
                    url = urlobj.get_full_url()
                    # Get headers
                    headers = urlobj.get_url_content_info()
                    if headers:
                        dom = urlobj.get_full_domain()
                        if self._projectcache.has_key(dom):
                            urldict = self._projectcache[dom]
                            d = urldict[url]
                            d['headers'] = headers
        
    def dump_headers(self):
        """ Dump the headers of the web pages
        downloaded into a DBM file. New in 1.4.5 """

        if self._cfg.urlheadersformat == 'dbm':
            import shelve
            
            # File is created in projectdir as
            # <project>-headers.dbm .
            dbmfile = os.path.join(self._cfg.projdir, "".join((self._cfg.project,'-headers.dbm')))
            extrainfo("Writing url headers database",dbmfile,"...")        
            shelf = shelve.open(dbmfile)
            
            links_dict = self.get_links_dictionary()
            for links in links_dict.values():
                for urlobj in links:
                    if urlobj:
                        url = urlobj.get_full_url()
                        # Get headers
                        headers = urlobj.get_url_content_info()
                        if headers:
                            shelf[url] = headers
                        
            shelf.close()
            if os.path.isfile(dbmfile):
                extrainfo("Wrote url headers database",dbmfile)
                return 0
            
            return -1
        else:
            extrainfo("Error: Unrecognized format",self._cfg.urlheadersformat,"for dumping url headers")
            return -1
    
    def localise_links(self):
        """ Localise all links (urls) of the downloaded html pages """

        # Dont confuse 'localising' with language localization.
        # This means just converting the outward (Internet) pointing
        # URLs in files to local files.
        
        info('Localising links of downloaded web pages...',)

        links_dict = self.get_links_dictionary()

        count = 0
        for filename in links_dict.keys():
            if os.path.exists(filename):
                links = links_dict[filename]
                info('Localizing links for',filename)
                if self.localise_file_links(filename, links)==0:
                    count += 1

        extrainfo('Localised links of',count,'web pages.')

    def localise_file_links(self, filename, links):
        """ Localise links for this file """

        data=''
        
        try:
            fw=open(filename, 'r+')
            data=fw.read()
            fw.seek(0)
            fw.truncate(0)
        except (OSError, IOError),e:
            return -1

        # Regex1 to replace ( at the end
        r1 = re.compile(r'\)+$')
        r2 = re.compile(r'\(+$')        
        
        # MOD: Replace any <base href="..."> line
        basehrefre = re.compile(r'<base href=.*>', re.IGNORECASE)
        if basehrefre.search(data):
            data = re.sub(basehrefre, '', data)
        
        for u in links:
            if not u: continue
            
            url_object = u
            typ = url_object.get_type()

            if url_object.is_image():
                http_str="src"
            else:
                http_str="href"

            v = url_object.get_original_url()
            if v == '/': continue

            # Somehow, some urls seem to have an
            # unbalanced parantheses at the end.
            # Remove it. Otherwise it will crash
            # the regular expressions below.
            v = r1.sub('', v)
            v2 = r2.sub('', v)
            
            # Bug fix, dont localize cgi links
            if typ != 'base':
                if url_object.is_cgi(): 
                    continue
                
                fullfilename = os.path.abspath( url_object.get_full_filename() )
                #extrainfo('Url=>',url_object.get_full_url())
                #extrainfo('Full filename=>',fullfilename)
                urlfilename=''

                # Modification: localisation w.r.t relative pathnames
                if self._cfg.localise==2:
                    urlfilename = url_object.get_relative_filename()
                elif self._cfg.localise==1:
                    urlfilename = fullfilename

                try:
                    oldnewmappings = GetObject('oldnewmappings')
                    newfilename = oldnewmappings[fullfilename]
                    if self._cfg.localise==2:
                        urlfilename = (os.path.split(newfilename))[1]
                    elif self._cfg.localise==1:
                        urlfilename = os.path.abspath(newfilename)
                except KeyError:
                    urlfilename = urlfilename

                # replace '\\' with '/'
                urlfilename = urlfilename.replace('\\','/')

                newurl=''
                oldurl=''
            
                # If we cannot get the filenames, replace
                # relative url paths will full url paths so that
                # the user can connect to them.
                if not os.path.exists(fullfilename):
                    # for relative links, replace it with the
                    # full url path
                    fullurlpath = url_object.get_full_url_sans_port()
                    newurl = "href=\"" + fullurlpath + "\""
                else:
                    # replace url with urlfilename
                    if typ == 'anchor':
                        anchor_part = url_object.get_anchor()
                        urlfilename = "".join((urlfilename, anchor_part))
                        # v = "".join((v, anchor_part))

                    if self._cfg.localise == 1:
                        newurl= "".join((http_str, "=\"", "file://", urlfilename, "\""))
                    else:
                        newurl= "".join((http_str, "=\"", urlfilename, "\""))

            else:
                newurl="".join((http_str,"=\"","\""))

            if typ != 'img':
                oldurl = "".join((http_str, "=\"", v, "\""))
                try:
                    oldurlre = re.compile("".join((http_str,'=','\\"?',v,'\\"?')))
                except Exception, e:
                    debug(str(e))
                    continue
                    
                # Get the location of the link in the file
                try:
                    if oldurl != newurl:
                        # info('Replacing %s with %s...' % (oldurl, newurl))
                        data = re.sub(oldurlre, newurl, data,1)
                except Exception, e:
                    debug(str(e))
                    continue
            else:
                try:
                    oldurlre1 = "".join((http_str,'=','\\"?',v,'\\"?'))
                    oldurlre2 = "".join(('href','=','\\"?',v,'\\"?'))
                    oldurlre = re.compile("".join(('(',oldurlre1,'|',oldurlre2,')')))
                except Exception, e:
                    debug(str(e))
                    continue
                
                http_strs=('href','src')
            
                for item in http_strs:
                    try:
                        oldurl = "".join((item, "=\"", v, "\""))
                        if oldurl != newurl:
                            info('Replacing %s with %s...' % (oldurl, newurl))                            
                            data = re.sub(oldurlre, newurl, data,1)
                    except:
                        pass

        try:
            fw.write(data)
            fw.close()
        except IOError, e:
            logconsole(e)

        return 0

    def print_project_info(self, statsd):
        """ Print project information """

        nlinks = statsd['links']
        nservers = statsd['extservers'] + 1
        nfiles = statsd['files']
        ndirs = statsd['extdirs'] + 1
        numfailed = statsd['failed']
        nretried = statsd['retries']
        fatal = statsd['fatal']
        fetchtime = statsd['fetchtime']
        nfilesincache = statsd['filesincache']
        nfilesinrepos = statsd['filesinrepos']

        # Bug fix, download time to be calculated
        # precisely...

        dnldtime = fetchtime

        strings = [('link', nlinks), ('server', nservers),
                   ('file', nfiles), ('file', nfilesinrepos),
                   ('directory', ndirs), ('link', numfailed), ('link', fatal),
                   ('link', nretried), ('file', nfilesincache) ]

        fns = map(plural, strings)
        info(' ')

        if fetchtime and nfiles:
            fps = (float(nfiles/dnldtime))
            fps = float((math.modf(fps*100.0))[1]/100.0)
        else:
            fps=0.0

        bytes = self._bytes

        ratespec='KB/sec'
        if bytes and dnldtime:
            bps = (float(bytes/dnldtime))/100.0
            bps = float((math.modf(bps*100.0))[1]/1000.0)
            if bps<1.0:
                bps *= 1000.0
                ratespec='bytes/sec'
        else:
            bps = 0.0

        self._cfg = GetObject('config')

        if self._cfg.simulate:
            info("HarvestMan crawl simulation of",self._cfg.project,"completed in",fetchtime,"seconds.")
        else:
            info('HarvestMan mirror',self._cfg.project,'completed in',fetchtime,'seconds.')
            
        if nlinks: info(nlinks,fns[0],'scanned in',nservers,fns[1],'.')
        else: info('No links parsed.')
        if nfiles: info(nfiles,fns[2],'written.')
        else:info('No file written.')
        
        if nfilesinrepos:
            info(nfilesinrepos,fns[3],wasOrWere(nfilesinrepos),'already uptodate in the repository for this project and',wasOrWere(nfilesinrepos),'not updated.')
        if nfilesincache:
            info(nfilesincache,fns[8],wasOrWere(nfilesincache),'updated from the project cache.')
            
        if fatal: info(fatal,fns[6],'had fatal errors and failed to download.')
        if bytes: info(bytes,' bytes received at the rate of',bps,ratespec,'.\n')

        # get current time stamp
        s=time.localtime()

        tz=(time.tzname)[0]

        format='%b %d %Y '+tz+' %H:%M:%S'
        tstamp=time.strftime(format, s)

        if not self._cfg.simulate:
            # Write stats to a stats file
            statsfile = self._cfg.project + '.hst'
            statsfile = os.path.abspath(os.path.join(self._cfg.projdir, statsfile))
            logconsole('\nWriting stats file ', statsfile , '...')
            # Append to files contents
            sf=open(statsfile, 'a')

            # Write url, file count, links count, time taken,
            # files per second, failed file count & time stamp
            infostr='url:'+self._cfg.url+','
            infostr +='files:'+str(nfiles)+','
            infostr +='links:'+str(nlinks)+','
            infostr +='dirs:'+str(ndirs)+','
            infostr +='failed:'+str(numfailed)+','
            infostr +='refetched:'+str(nretried)+','
            infostr +='fatal:'+str(fatal)+','
            infostr +='elapsed:'+str(fetchtime)+','
            infostr +='fps:'+str(fps)+','
            infostr +='kbps:'+str(bps)+','
            infostr +='timestamp:'+tstamp
            infostr +='\n'
            
            sf.write(infostr)
            sf.close()
            
            logconsole('Done.')

    def dump_urltree(self, urlfile):
        """ Dump url tree to a file """

        # This function provides a little
        # more functionality than the plain
        # dump_urls in the rules module.
        # This creats an html file with
        # each url and its children below
        # it. Each url is a hyperlink to
        # itself on the net if the file
        # is an html file.

        try:
            if os.path.exists(urlfile):
                os.remove(urlfile)
        except OSError, e:
            logconsole(e)

        moreinfo('Dumping url tree to file', urlfile)
        fextn = ((os.path.splitext(urlfile))[1]).lower()        
        
        try:
            f=open(urlfile, 'w')
            if fextn in ('', '.txt'):
                self.dump_urltree_textmode(f)
            elif fextn in ('.htm', '.html'):
                self.dump_urltree_htmlmode(f)
            f.close()
        except Exception, e:
            logconsole(e)
            return -1

        debug("Done.")

        return 0

    def dump_urltree_textmode(self, stream):
        """ Dump urls in text mode """

        linksdict = self.get_links_dictionary()
        
        for f in linksdict.keys ():
            idx = 0
            links = linksdict[f]

            children = []
            for link in links:
                if not link: continue

                # Get base link, only for first
                # child url, since base url will
                # be same for all child urls.
                if idx==0:
                    children = []
                    base_url = link.get_base_urlobject().get_full_url()
                    stream.write(base_url + '\n')

                childurl = link.get_full_url()
                if childurl and childurl not in children:
                    stream.write("".join(('\t',childurl,'\n')))
                    children.append(childurl)

                idx += 1


    def dump_urltree_htmlmode(self, stream):
        """ Dump urls in html mode """

        linksdict = self.get_links_dictionary()

        # Write html header
        stream.write('<html>\n')
        stream.write('<head><title>')
        stream.write('Url tree generated by HarvestMan - Project %s'
                     % GetObject('config').project)
        stream.write('</title></head>\n')

        stream.write('<body>\n')

        stream.write('<p>\n')
        stream.write('<ol>\n')
        
        for f in linksdict.keys ():
            idx = 0
            links = linksdict[f]

            children = []
            for link in links:
                if not link: continue

                # Get base link, only for first
                # child url, since base url will
                # be same for all child urls.
                if idx==0:
                    children = []                   
                    base_url = link.get_base_urlobject().get_full_url()
                    stream.write('<li>')                    
                    stream.write("".join(("<a href=\"",base_url,"\"/>",base_url,"</a>")))
                    stream.write('</li>\n')
                    stream.write('<p>\n')
                    stream.write('<ul>\n')
                                 
                childurl = link.get_full_url()
                if childurl and childurl not in children:
                    stream.write('<li>')
                    stream.write("".join(("<a href=\"",childurl,"\"/>",childurl,"</a>")))
                    stream.write('</li>\n')                    
                    children.append(childurl)
                    
                idx += 1                


            # Close the child list
            stream.write('</ul>\n')
            stream.write('</p>\n')
            
        # Close top level list
        stream.write('</ol>\n')        
        stream.write('</p>\n')
        stream.write('</body>\n')
        stream.write('</html>\n')

    def get_url_threadpool(self):
        """ Return the URL thread-pool object """

        return self._urlThreadPool

class HarvestManController(tg.Thread):
    """ A controller class for managing exceptional
    conditions such as file limits. Right now this
    is written with the sole aim of managing file
    & time limits, but could get extended in future
    releases. """

    # NOTE: This class's object does not get registered
    def __init__(self):
        self._dmgr = GetObject('datamanager')
        self._tq =  GetObject('trackerqueue')
        self._cfg = GetObject('config')
        self._exitflag = False
        self._conn = {}
        tg.Thread.__init__(self, None, None, 'HarvestMan Control Class')

    def run(self):
        """ Run in a loop looking for
        exceptional conditions """

        while not self._exitflag:
            # Wake up every second and look
            # for exceptional conditions
            time.sleep(1.0)
            self.__manage_time_limits()
            self.__manage_file_limits()

    def stop(self):
        """ Stop this thread """

        self._exitflag = True

    def terminator(self):
        """ The function which terminates the program
        in case of an exceptional condition """

        # This somehow got deleted in HarvestMan 1.4.5
        
        tq = GetObject('trackerqueue')
        tq.terminate_threads()
        
    def __manage_fetcher_connections(self):
        """ Manage timeouts for fetcher downloads using
        a dictionary - New in 1.4.5 final """

        # Not enabled in this version!
        for key, value in self._conn.items():
            # Key is the thread itself
            tracker = key
            # If this tracker is not in a download stage, skip it.
            if tracker.get_status() != 1:
                continue
            # Value is a two tuple of timeout-count, connection timestamp
            count, start_time = value
            # Check time gap
            time_gap = time.time() - start_time
            # Check if it is greater than allowed time-out
            if time_gap>self._cfg.fetchertimeout:
                # If number of violations is two, kill the thread
                if count>=2:
                    try:
                        # debug('Terminating thread',tracker)
                        self._tq.recycle_thread(tracker)
                    except Exception, e:
                        pass

                    # debug('Running threads=>',tg.activeCount())
                    del self._conn[tracker]
                else:
                    # Increment violation count and re-set
                    # time-stamp
                    count += 1
                    self._conn[tracker] = count, time.time()

    def __manage_time_limits(self):
        """ Manage limits on time for the project """

        # If time limit is not set, return
        if self._cfg.timelimit == -1:
            return -1
        
        if sys.platform == 'win32' or os.name=='nt':
            t2=time.clock()
        else:
            t2=time.time()

        timediff = float((math.modf((t2-self._cfg.starttime)*100.0)[1])/100.0)
        timemax = self._cfg.timelimit
        
        if timediff >= timemax -1:
            moreinfo('Specified time limit of',timemax ,'seconds reached!')            
            self.terminator()

        return 0

    def __manage_file_limits(self):
        """ Manage limits on maximum file count """

        ddict = self._dmgr._downloaddict
        
        lsaved = len(ddict.get('_savedfiles', []))
        lmax = self._cfg.maxfiles

        if lsaved < lmax:
            return -1
        
        if lsaved == lmax:
            moreinfo('Specified file limit of',lmax ,'reached!')
            self.terminator()
            
        # see if some tracker still managed to download
        # files while we were killing, then delete them!
        if lsaved > lmax:
            diff = lsaved - lmax
            savedcopy = (ddict['_savedfiles'])[0:]

            for x in xrange(diff):
                # 2 bugs: fixed a bug where the deletion
                # was not controlled
                lastfile = savedcopy[lsaved - x -1]

                # sometimes files may not be there, attempt
                # to delete only if file is there (makes sense)
                if os.path.exists(lastfile):
                    try:
                        extrainfo('Deleting file ', lastfile)
                        os.remove(lastfile)
                        (ddict['_deletedfiles']).append(lastfile)
                        ddict['_savedfiles'].remove(lastfile)
                    except (OSError, IndexError, ValueError), e:
                        logconsole(e)

        return 0
                    
    def log_connection(self, conn, thread_conn):
        """ Log a connection for a download (Fetcher) thread """

        # To be enabled in next version!
        
        # Logic: The idea is to keep track of fetcher threads
        # which gets stuck while downloading a URL. The log
        # is a dictionary entry, a tuple of two values - The
        # number of times the download time exceeded the thread
        # timeout value and the timestamp of the download.
        self._conn[thread_conn] = (0, time.time())


