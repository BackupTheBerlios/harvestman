# -- coding: latin-1
""" rules.py - Rules checker module for HarvestMan.
    This module is part of the HarvestMan program.

     Author: Anand B Pillai <abpillai at gmail dot com>

    Modification History
    --------------------

   Jan 8 2006          Anand    Updated this file from EIAO
                                repository to get fixes for robot
                                rules. Removed EIAO specific
                                code.

                                Put ext check rules before robots
                                check to speed up things.
   Jan 10 2006          Anand    Converted from dos to unix format
                                (removed Ctrl-Ms).

   April 11 2007        Anand   Not doing I.P comparison for
                                non-robots.txt URLs in __compare_domains
                                method as it is erroneous.

   Copyright (C) 2004 Anand B Pillai.
                                
"""

__version__ = '2.0 b1'
__author__ = 'Anand B Pillai'

import socket
import re
import os
import time
import copy

import robotparser

from common.common import *
from common.methodwrapper import MethodWrapperMetaClass

import urlparser

# Defining pluggable functions
__plugins__ = {'violates_basic_rules_plugin': 'HarvestManRulesChecker:violates_basic_rules'}

# Defining functions with callbacks
__callbacks__ = {'violates_basic_rules_callback' : 'HarvestManRulesChecker:violates_basic_rules'}

class HarvestManRulesChecker(object):
    """ Class which checks the download rules for urls. These
    rules include depth checks, robot.txt rules checks, filter
    checks, external server/directory checks, duplicate url
    checks, maximum limits check etc. """

    # For supporting callbacks
    __metaclass__ = MethodWrapperMetaClass
    
    def __init__(self):

        self._links = []
        self._sourceurls = []
        self._filter = []
        self._extservers = []
        self._extdirs = []
        self._rexplist = []
        self._wordstr = '[\s+<>]'
        self._robots  = {}
        self._robocache = []
        self._logger = GetObject('logger')
        # For hash sums of page data
        self._pagehash = {}
        
        # Configure robotparser object if rep rule is specified
        self._configobj = GetObject('config')
        # Create junk filter if specified
        if self._configobj.junkfilter:
            self.junkfilter = JunkFilter()
        else:
            self.junkfilter = None

    def get_state(self):
        """ Return a snapshot of the current state of this
        object and its containing threads for serializing """
        
        d = {}
        d['_links'] = self._links[:]
        d['_sourceurls'] = self._sourceurls[:]
        d['_filter'] = self._filter[:]
        d['_extservers'] = self._extservers[:]
        d['_extdirs'] = self._extdirs[:]
        # d['_robots'] = self._robots.copy()
        d['_robocache'] = self._robocache[:]
        d['_pagehash'] = self._pagehash.copy()

        return copy.deepcopy(d)

    def set_state(self, state):
        """ Set state to a previous saved state """

        self._links = state.get('_links',[])
        self._sourceurls = state.get('_sourceurls', [])
        self._filter = state.get('_filter', [])
        self._extservers = state.get('_extservers', [])
        self._extdirs = state.get('_extdirs', [])
        self._robocache = state.get('_robocache', [])                
        self._pagehash = state.get('_pagehash', {})

        self._configobj = GetObject('config')
        # Create junk filter if specified
        if self._configobj.junkfilter:
            self.junkfilter = JunkFilter()
        else:
            self.junkfilter = None
        
    def violates_basic_rules(self, urlObj):
        """ Check the basic rules for this url object,
        This function returns True if the url object
        violates the rules, else returns False """

        url = urlObj.get_full_url()

        # if this url exists in filter list, return
        # True rightaway
        try:
            self._filter.index(url)
            return True
        except ValueError:
            pass

       # now apply the url filter
        if self.__apply_url_filter(url):
            extrainfo("Custom filter - filtered ", url)
            return True

        # now apply the junk filter
        if self.junkfilter:
            if not self.junkfilter.check(urlObj):
                extrainfo("Junk Filter - filtered", url)
                return True

        # check if this is an external link
        if self.__is_external_link( urlObj ):
            extrainfo("External link - filtered ", urlObj.get_full_url())
            return True

        # now apply REP
        if self.__apply_rep(urlObj):
            extrainfo("Robots.txt rules prevents download of ", url)
            return True

        # depth check
        if self.__apply_depth_check(urlObj):
            extrainfo("Depth exceeds - filtered ", urlObj.get_full_url())
            return True

        return False

    def add_to_filter(self, link):
        """ Add the link to the filter list """

        try:
            self._filter.index(link)
        except:
            self._filter.append(link)

    def __compare_domains(self, domain1, domain2, robots=False):
        """ Compare two domains (servers) first by
        ip and then by name and return True if both point
        to the same server, return False otherwise. """

        # For comparing robots.txt file, first compare by
        # ip and then by name.
        if robots: 
            firstval=self.__compare_by_ip(domain1, domain2)
            if firstval:
                return firstval
            else:
                return self.__compare_by_name(domain1, domain2)

        # otherwise, we do only a name check
        else:
            return self.__compare_by_name(domain1, domain2)

    def __get_base_server(self, server):
        """ Return the base server name of  the passed
        server (domain) name """

        # If the server name is of the form say bar.foo.com
        # or vodka.bar.foo.com, i.e there are more than one
        # '.' in the name, then we need to return the
        # last string containing a dot in the middle.
        if server.count('.') > 1:
            dotstrings = server.split('.')
            # now the list is of the form => [vodka, bar, foo, com]

            # Return the last two items added with a '.'
            # in between
            return "".join((dotstrings[-2], ".", dotstrings[-1]))
        else:
            # The server is of the form foo.com or just "foo"
            # so return it straight away
            return server

    def __compare_by_name(self, domain1, domain2):
        """ Compare two servers by their names. Return True
        if similar, False otherwise """

        # first check if both domains are same
        if domain1.lower() == domain2.lower(): return True
        extrainfo('Comparing domains %s and %s...' % (domain1, domain2))
        if not self._configobj.subdomain:
            # Checks whether the domain names belong to
            # the same base server, if the above config
            # variable is set. For example, this will
            # return True for two servers like server1.foo.com
            # and server2.foo.com or server1.base and server2.base
            baseserver1 = self.__get_base_server(domain1)
            baseserver2 = self.__get_base_server(domain2)
            # extrainfo('Server1:%s, Server2:%s' % (baseserver1, baseserver2))
            
            if baseserver1.lower() == baseserver2.lower():
                return True
            else:
                return False
        else:
            # if the subdomain variable is set
            # will return False for two servers like
            # server1.foo.com and server2.foo.com i.e
            # with same base domain but different
            # subdomains.
            return False

    def __compare_by_ip(self, domain1, domain2):
        """ Compare two servers by their ip address. Return
        True if same, False otherwise """

        try:
            ip1 = socket.gethostbyname(domain1)
            ip2 = socket.gethostbyname(domain2)
        except Exception:
            return False

        if ip1==ip2: return True
        else: return False

    def __apply_rep(self, urlObj):
        """ See if the robots.txt file on the server
        allows fetching of this url. Return 0 on success
        (fetching allowed) and 1 on failure(fetching blocked) """

        # NOTE: Rewrote this method completely
        # on Nov 18 for 1.4 b2.

        # robots option turned off
        if self._configobj.robots==0: return False
        
        domport = urlObj.get_full_domain_with_port()
        # The robots.txt file url
        robotsfile = "".join((domport, '/robots.txt'))

        # Check #1 - See if this site does not
        # have a robots.txt, then no need to bother.
        try:
            self._filter.index(robotsfile)
            return 0
        except ValueError:
            pass

        url_directory = urlObj.get_url_directory()

        # Check #2: Check if this directory
        # is already there in the white list
        try:
            self._robocache.index(url_directory)
            return 0
        except ValueError:
            pass

        # Check #3
        # if this url exists in filter list, return
        # True rightaway
        try:
            self._filter.index(urlObj.get_full_url())
            return 1
        except ValueError:
            pass

        try:
            rp = self._robots[domport]
            # Check #4
            # If there is an entry, but it
            # is None, it means there is no
            # robots.txt file in the server
            # (see below). So return False.
            if not rp: return 0
        except KeyError:
            # Not there, create a fresh
            # one and add it.
            rp = robotparser.RobotFileParser()
            rp.set_url(robotsfile)
            ret = rp.read()
            # Check #5                
            if ret==-1:
                # no robots.txt file
                # Set the entry for this
                # server as None, so next
                # time we dont need to do
                # this operation again.
                self._robots[domport] = None
                return 0
            else:
                # Set it
                self._robots[domport] = rp

        # Get user-agent from Spider
        ua = GetObject('USER_AGENT')
        
        # Check #6
        if rp.can_fetch(ua, url_directory):
            # Add to white list
            self._robocache.append(url_directory)
            return 0

        # Cannot fetch, so add to filter
        # for quick look up later.
        self.add_to_filter(urlObj.get_full_url())
        
        return 1

    def apply_word_filter(self, data):
        """ Apply the word filter """

        cfg = GetObject('config')
        if cfg.wordfilter:
            if cfg.wordfilterre.search(data):
                return True
            else:
                return False

        return True

    def __apply_url_filter(self, url):
        """ See if we have a filter matching the url.
        Return 1 for blocking the url and 0 for allowing it """

        inclfilter = self._configobj.inclfilter
        exclfilter = self._configobj.exclfilter

        # neither filters are enabled, return 0
        if not inclfilter and not exclfilter: return 0

        # We always check inclusion filter first since it is
        # normally more specific than exclusion filter. Someone
        # can request to not fetch any url containing /images/
        # in the path, but still fetch the particular path
        # /preferred/images. It will work only if we check for
        # inclusion first and exclusion later.
        inclcheck,exclcheck=-1,-1
        matchincl, matchexcl=False,False

        if inclfilter:
            inclcheck=1
            # see if we have a match
            for f in inclfilter:
                m=f.search(url)
                if m:
                    extrainfo('Go-through filter for url ', url, 'found')
                    matchincl=True
                    inclcheck=0
                    break

        if exclfilter:
            exclcheck=0
            # see if we have a match
            for f in exclfilter:
                m=f.search(url)
                if m:
                    extrainfo('No-pass filter for url ', url, 'found')
                    matchexcl=True
                    self.add_to_filter(url)               
                    exclcheck=1
                    break

        if inclcheck==1:
            extrainfo("Inclfilter does not allow this url", url)
        if exclcheck==0:
            extrainfo("Exclfilter allows this url", url)

        # if exclfilter and inclfilter returns different results
        # (exclfilter denys, inclfilter allows)
        # we check the order of the filters in the global filter. Whichever
        # comes first has precedence.
        if inclcheck == 0 and exclcheck == 1:
            globalfilter=self._configobj.allfilters
            try:
                indexincl=globalfilter.index(matchincl)
            except:
                indexincl=-1
            try:
                indexexcl=globalfilter.index(matchexcl)
            except:
                indexexcl=-1
            if indexincl != -1 and indexexcl != -1:
                if indexincl < indexexcl:
                    # inclusion filter has precedence
                    return inclcheck
                else:
                    # exclusion filter has precedence
                    return exclcheck
            else:
                # error, return allow (0)
                return 0
        else:
            # return whichever matched
            if inclcheck != -1:
                return inclcheck
            elif exclcheck != -1:
                return exclcheck
            # none matched, allow it
            else:
                return 0 

        # We wont reach here
        return 0

    def __apply_server_filter(self, urlObj):
        """ See if we have a filter matching the server of
        this url. Return 1 on success(blocked) and 0 on failure
        (allowed) """

        server = urlObj.get_domain()

        serverinclfilter = self._configobj.serverinclfilter
        serverexclfilter = self._configobj.serverexclfilter

        if not serverexclfilter and not serverinclfilter: return 0

        # We always check inclusion filter first since it is
        # normally more specific than exclusion filter. Someone
        # can request to not fetch any url containing /images/
        # in the path, but still fetch the particular path
        # /preferred/images. It will work only if we check for
        # inclusion first and exclusion later.
        inclcheck,exclcheck=-1,-1
        matchincl, matchexcl=False,False

        url = urlObj.get_full_url()

        if serverinclfilter:
            inclcheck = 1

            for f in serverinclfilter:
                # see if we have a match
                m=re.search(re.compile(f,re.IGNORECASE), server)

                if m:
                    extrainfo('Go-through filter for url ', url, 'found')
                    matchincl=f
                    inclcheck=0
                    break

        if serverexclfilter:
            exclcheck = 1
            for f in serverexclfilter:
                # see if we have a match
                m=re.search(re.compile(f,re.IGNORECASE), server)

                if m:
                    extrainfo('No-pass filter for url ', url, 'found')
                    matchexcl=f
                    self.add_to_filter(url)               
                    exclcheck=1
                    break

        if inclcheck==1:
            extrainfo("Inclfilter does not allow this url", url)
        if exclcheck==0:
            extrainfo("Exclfilter allows this url", url)

        # if exclfilter and inclfilter returns different results
        # (exclfilter denys, inclfilter allows)
        # we check the order of the filters in the global filter. Whichever
        # comes first has precedence.
        if inclcheck == 0 and exclcheck == 1:
            globalfilter=self._configobj.allserverfilters
            try:
                indexincl=globalfilter.index(matchincl)
            except:
                indexincl=-1
            try:
                indexexcl=globalfilter.index(matchexcl)
            except:
                indexexcl=-1

            if indexincl != -1 and indexexcl != -1:
                if indexincl < indexexcl:
                    # inclusion filter has precedence
                    return inclcheck
                else:
                    # exclusion filter has precedence
                    return exclcheck
            else:
                # error, return allow (0)
                return 0
        else:
            # return whichever matched
            if inclcheck != -1:
                return inclcheck
            elif exclcheck != -1:
                return exclcheck
            # none matched, allow it
            else:
                return 0 

        # We wont reach here
        return 0

    def is_under_starting_directory(self, urlObj):
        """ Check whether the url in the url object belongs
        to the same directory as the starting url for the
        project """

        directory = urlObj.get_url_directory()
        # Get the tracker queue object
        tq = GetObject('trackerqueue')
        baseUrlObj = tq.get_base_urlobject()
        if not baseUrlObj:
            return True

        bdir = baseUrlObj.get_url_directory()

        # Look for bdir inside dir
        index = directory.find(bdir)

        if index == 0:
            return True

        # Sometimes a simple string match
        # is not good enough. May be both
        # the directories are the same but
        # the server names are slightly different
        # ex: www-106.ibm.com and www.ibm.com
        # for developerworks links.

        # Check if both of them are in the same
        # domain
        if self.__compare_domains(urlObj.get_domain(), baseUrlObj.get_domain()):
            # Get url directory sans domain
            directory = urlObj.get_url_directory_sans_domain()
            bdir = baseUrlObj.get_url_directory_sans_domain()

            # Check again
            if directory.find(bdir) == 0:
                return True

        return False
            
    def is_external_server_link(self, urlObj):
        """ Check whether the url in the url object belongs to
        an external server """

        # Get the tracker queue object
        tq = GetObject('trackerqueue')
        baseUrlObj = tq.get_base_urlobject()
        if not baseUrlObj:
            return False

        # Check based on the server
        server = urlObj.get_domain()
        baseserver = baseUrlObj.get_domain()

        return not self.__compare_domains( server, baseserver )

    def __is_external_link(self, urlObj):
        """ Check if the url is an external link relative to starting url,
        using the download rules set by the user """

        # Example.
        # Assume our start url is 'http://www.server.com/files/images/index.html"
        # Then any url which starts with another server name or at a level
        # above the start url's base directory on the same server is considered
        # an external url
        # i.e, http://www.yahoo.com will be external because of
        # 1st reason &
        # http://www.server.com/files/search.cgi will be external link because of
        # 2nd reason.
        # External links ?

        # if under the same starting directory, return False
        if self.is_under_starting_directory(urlObj):
            return False

        directory = urlObj.get_url_directory()

        tq = GetObject('trackerqueue')
        baseUrlObj = tq.get_base_urlobject()
        if not baseUrlObj:
            return False

        if urlObj.get_type() == 'stylesheet':
            if self._configobj.getstylesheets: return False

        elif urlObj.get_type() == 'image':
            if self._configobj.getimagelinks: return False

        if not self.is_external_server_link(urlObj):
            if self._configobj.fetchlevel==0:
                return True
            elif self._configobj.fetchlevel==3:
                # check for the directory of the parent url
                # if it is same as starting directory, allow this
                # url, else deny
                try:
                    parentUrlObj = urlObj.get_base_urlobject()
                    if not parentUrlObj:
                        return False

                    parentdir = parentUrlObj.get_url_directory()
                    bdir = baseUrlObj.get_url_directory()

                    if parentdir == bdir:
                        self.__increment_ext_directory_count(directory)
                        return False
                    else:
                        return True
                except urlparser.HarvestManUrlParserError, e:
                    logconsole(e)
                    
            elif self._configobj.fetchlevel > 0:
                # this option takes precedence over the
                # extpagelinks option, so set extpagelinks
                # option to true.
                self._configobj.epagelinks=1
                # do other checks , just fall through

            # Increment external directory count
            directory = urlObj.get_url_directory()

            res=self.__ext_directory_check(directory)
            if not res:
                extrainfo("External directory error - filtered!")
                self.add_to_filter(urlObj.get_full_url())
                return True

            # Apply depth check for external dirs here
            if self._configobj.extdepth:
                if self.__apply_depth_check(urlObj, mode=2):
                    return True

            if self._configobj.epagelinks:
                # We can get external links belonging to same server,
                # so this is not an external link
                return False
            else:
                # We cannot get external links belonging to same server,
                # so this is an external link
                self.add_to_filter(urlObj.get_full_url())
                return True
        else:
            # Both belong to different base servers
            if self._configobj.fetchlevel==0 or self._configobj.fetchlevel == 1:
                return True
            elif self._configobj.fetchlevel==2 or self._configobj.fetchlevel==3:
                # check whether the baseurl (parent url of this url)
                # belongs to the starting server. If so allow fetching
                # else deny. ( we assume the baseurl path is not relative! :-)
                try:
                    parentUrlObj = urlObj.get_base_urlobject()
                    baseserver = baseUrlObj.get_domain()

                    if not parentUrlObj:
                        return False

                    server = urlObj.get_domain()
                    if parentUrlObj.get_domain() == baseserver:
                        self.__increment_ext_server_count(server)
                        return False
                    else:
                        return True
                except urlparser.HarvestManUrlParserError, e:
                    logconsole(e)
                    
            elif self._configobj.fetchlevel>3:
                # this option takes precedence over the
                # extserverlinks option, so set extserverlinks
                # option to true.
                self._configobj.eserverlinks=1
                # do other checks , just fall through

            res = self.__ext_server_check(urlObj.get_domain())

            if not res:
                self.add_to_filter(urlObj.get_full_url())
                return True

            # Apply filter for servers here
            if self.__apply_server_filter(urlObj):
                return True

            # Apply depth check for external servers here
            if self._configobj.extdepth:
                if self.__apply_depth_check(urlObj, mode=2):
                    return True

            if self._configobj.eserverlinks:
                # We can get links belonging to another server, so
                # this is NOT an external link
                return False
            else:
                # We cannot get external links beloning to another server,
                # so this is an external link
                self.add_to_filter(urlObj.get_full_url())
                return True

        # We should not reach here
        return False

    def __apply_depth_check(self, urlObj, mode=0):
        """ Apply the depth setting for this url, if any """

        # depth variable is -1 means no depth-check
        tq = GetObject('trackerqueue')
        baseUrlObj = tq.get_base_urlobject()
        if not baseUrlObj:
            return False

        reldepth = urlObj.get_relative_depth(baseUrlObj, mode)

        if reldepth != -1:
            # check if this exceeds allowed depth
            if mode == 0 and self._configobj.depth != -1:
                if reldepth > self._configobj.depth:
                    self.add_to_filter(urlObj.get_full_url())
                    return True
            elif mode == 2 and self._configobj.extdepth:
                if reldepth > self._configobj.extdepth:
                    self.add_to_filter(urlObj.get_full_url())
                    return True

        return False

    def __ext_directory_check(self, directory):
        """ Check whether the directory <directory>
        should be considered external """

        index=self.__increment_ext_directory_count(directory)

        # Are we above a prescribed limit ?
        if self._configobj.maxextdirs and len(self._extdirs)>self._configobj.maxextdirs:
            if index != -1:
                # directory index was below the limit, allow its urls
                if index <= self._configobj.maxextdirs:
                    return True
                else:
                    # directory index was above the limit, block its urls
                    return False
            # new directory, block its urls
            else:
                return False
        else:
            return True

    def __ext_server_check(self, server):
        """ Check whether the server <server> should be considered
        external """

        index=self.__increment_ext_server_count(server)

        # are we above a prescribed limit ?
        if self._configobj.maxextservers and len(self._extservers)>self._configobj.maxextservers:
            if index != -1:
                # server index was below the limit, allow its urls
                if index <= self._configobj.maxextservers:
                    return True
                else:
                    return False
            # new server, block its urls
            else:
                return False
        else:
            return True

    def __increment_ext_directory_count(self, directory):
        """ Increment the external dir count """

        index=-1
        try:
            index=self._extdirs.index(directory)
        except:
            self._extdirs.append(directory)

        return index

    def __increment_ext_server_count(self,server):
        """ Increment the external server count """

        index=-1
        try:
            index=self._extservers.index(server)
        except:
            self._extservers.append(server)

        return index

    def is_duplicate_link(self, link):
        """ Duplicate url check """

        return self.add_link(link)

    def add_link(self, url):
        """ Add the passed url to the links list after checking
        for duplicates """

        # Return True if the url is present in
        # the list, False otherwise.
        try:
            self._links.index(url)
            return True
        except:
            self._links.append(url)
            return False

    def add_source_link(self, surl):
        """ Add a source url """

        try:
            self._sourceurls.index(surl)
            return True
        except:
            self._sourceurls.append(surl)
            return False

    def check_duplicate_content(self, urlobj, datahash):
        """ Check if content for this URL is already there """

        # Note - we allow same content from different domains
        
        if datahash in self._pagehash:
            # Check if earlier page was from this domain
            dom = self._pagehash[datahash]
            return (dom == urlobj.get_domain())
        else:
            self._pagehash[datahash] = urlobj.get_domain()
            return False
        
    def get_stats(self):
        """ Return statistics as a 3 tuple. This returns
        a 3 tuple of number of links, number of servers, and
        number of directories in the base server parsed by
        url trackers """

        numlinks=len(self._links)
        numservers=len(self._extservers)
        numdirs=len(self._extdirs)

        return (numlinks, numservers, numdirs)

    def dump_urls(self, urlfile):
        """ Write all parsed urls to a file """

        if os.path.exists(urlfile):
            try:
                os.remove(urlfile)
            except OSError, e:
                logconsole(e)
                return

        moreinfo('Dumping url list to file', urlfile)

        try:
            f=open(urlfile, 'w')

            for link in self._links:
                f.write(link + '\n')

            f.close()
        except Exception, e:
            logconsole(e)
            
        debug('Done.') 

    def make_filters(self):
        """ This function creates the filter regexps
        for url/server filtering """

        # url filter string
        urlfilterstr = self._configobj.urlfilter
        # print 'URL FILTER STRING=>',urlfilterstr
        
        url_filters = self.__make_filter(urlfilterstr)
        # print 'URL FILTERS=>',url_filters
        
        self._configobj.set_option('urlfilterre_value', url_filters)

        # server filter string
        serverfilterstr = self._configobj.serverfilter
        server_filters = self.__make_filter(serverfilterstr)
        self._configobj.set_option('serverfilterre_value', server_filters)

        #  url/server priority filters
        urlprioritystr = self._configobj.urlpriority
        # The return is a dictionary
        url_priorities = self.__make_priority(urlprioritystr)

        self._configobj.set_option('urlprioritydict_value', url_priorities)

        serverprioritystr = self._configobj.serverpriority
        # The return is a dictionary        
        server_priorities = self.__make_priority(serverprioritystr)

        self._configobj.set_option('serverprioritydict_value', server_priorities)

        # word filter list
        wordfilterstr = self._configobj.wordfilter
        if wordfilterstr:
            word_filter = self.__make_word_filter(wordfilterstr)
            self._configobj.wordfilterre = word_filter

    def __make_priority(self, pstr):
        """ Generate a priority dictionary from the priority string """

        # file priority is based on file extensions &
        # server priority based on server names

        # Priority string is of the form...
        # str1+pnum1,str2-pnum2,str3+pnum3 etc...
        # Priority range is from [-5 ... +5]

        # Split the string based on commas
        pr_strs = pstr.split(',')

        # For each string in list, create a dictionary
        # with the string as key and the priority (including
        # sign) as the value.

        d = {}
        for s in pr_strs:
            if s.find('+') != -1:
                key, val = s.split('+')
                val = int(val)

            elif s.find('-') != -1:
                key, val = s.split('-')
                val = -1*int(val)
            else:
                continue

            # Since we dont allow values outside
            # the range [-5 ..5] skip such values
            if val not in range(-5,6): continue
            d[key.lower()] = val

        return d

    def __make_filter(self, fstr,servers=0):
        """ Function used to convert url filter strings
        to python regular expresssions """

        # First replace any ''' with ''
        fstr=fstr.replace("'",'')            
        # regular expressions to include
        include=[]
        # regular expressions to exclude        
        exclude=[]
        # all regular expressions
        all=[]

        index=0
        previndex=-1
        fstr += '+'
        for c in fstr:
            if c in ('+','-'):
                subs=fstr[(previndex+1):index]
                if subs: all.append(subs)
                previndex=index
            index+=1

        l=fstr.split('+')

        for s in l:
            l2=s.split('-')
            for x in xrange(len(l2)):
                s=l2[x]
                if s=='': continue
                if x==0:
                    include.append(s)
                else:
                    exclude.append(s)

        # print 'Exclude=>',exclude
        # print 'Include=>',include
        
        exclusionfilter=self.__create_filter(exclude,servers)
        inclusionfilter=self.__create_filter(include,servers)
        allfilter = self.__create_filter(all, servers)

        # return a 3 tuple of (inclusionfilter, exclusionfilter, allfilter)
        return (inclusionfilter, exclusionfilter, allfilter)

    def __create_filter(self, strlist, servers=0):
        """ Create a python regular expression based on
        the list of filter strings provided as input """

        refilter = []
        if servers:
            serverfilter=[]
            for s in strlist:
                # First replace any ''' with ''
                s=s.replace("'",'')
                # Here asteriks have a meaning, they should match
                # anything
                s=s.replace('*', '.*')
                serverfilter.append(s)

            return serverfilter

        for s in strlist:
            fstr = ''
            # First replace any ''' with ''
            extn=s.replace("'",'')            
            # Then we remove the asteriks
            s=s.replace('*','.*')
            # Type 1 filter-> they begin with '.' now
            # Find out position of '.'
            pos=s.rfind('.')
            if pos == 0:
                s = "".join(("\\", s))
                # Append a '.*$' to the string
                s += '$'
                fstr += s
            # Type 3 filter
            # These will be the form of <something>/.<extn> now
            elif s[pos-1] == '/':
                # get that <something>
                prefix = s[:(pos-1)]
                # get the <extn>
                extn = s[(pos+1):]
                myfilter = prefix
                myfilter += '/(?=\w+.'
                myfilter += extn
                myfilter += ')'
                fstr += myfilter
            # All other cases are considered Type 2 filters
            # i.e, plain strings
            else:
                fstr += s

            # print 'Fstr=>',fstr
            
            refilter.append(re.compile(fstr, re.IGNORECASE))

        return refilter

    def __parse_word_filter(self, s):

        scopy = s[:]
        oparmatch, clparmatch = False, False
        index = scopy.rfind('(')

        if index != -1:
            oparmatch = True
            index2 = scopy.find(')', index)

            if index2 != -1:
                clparmatch = True
                newstr = scopy[index+1:index2]
                # if the string is only of whitespace chars, skip it
                wspre = re.compile('^\s*$')
                if not wspre.match(newstr):
                    self._rexplist.append(newstr)
                replacestr = ''.join(('(', newstr, ')'))
                scopy = scopy.replace(replacestr, '')
                self.__parse_word_filter(scopy)

        if not clparmatch and not oparmatch:
            if scopy: self._rexplist.append(scopy)


    def __make_not_expr(self, s):
        """ Make a NOT expression """

        if s.find('!') == 0:
            return ''.join(('(?!', s[1:], ')'))
        else:
            return s

    def __is_inbetween(self, l, elem):
        """ Find out if an element is in between in a list """

        i = l.index(elem)
        if i == -1: return False

        loflist = len(l)

        if i>1:
            if i in xrange(1, loflist -1):
                return True
            else:
                return False
        elif i==1:
            return True
        elif i==0:
            if loflist==1:
                return True
            else:
                return False

    def __make_word_filter(self, s):
        """ Create a word filter rule for HarvestMan """

        # Word filter strings can be simple or compound.
        # Simple strings are strings that can stand for a
        # word or a string.
        # Egs: Python.
        # Complex strings are expressions that can mean
        # boolean logic.
        # Egs: Python & Perl, Python || Perl, (Python || Perl) & Ruby

        # If more than one paren group found, replace | with (|)
        clparen = s.count(')')
        oparen  = s.count('(')
        if oparen != clparen:
            logconsole('Error in word regular expression')
            return None

        self.__parse_word_filter(s)
        # if NOT is one of the members, reverse
        # the list.
        if '!' in self._rexplist:
            self._rexplist.reverse()

        rstr = self.__make_word_regexp( self._rexplist )
        r = re.compile( rstr, re.IGNORECASE )
        return r

    def __make_word_regexp(self, mylist):


        is_list = True

        if type(mylist) is str:
            is_list = False
            elem =  mylist
        elif type(mylist) is list:
            elem = mylist[0]

        if type(elem) is list:
            elem = elem[0]

        eor = False
        if not is_list or len(mylist) == 1:
            eor = True

        s=''

        # Implementing NOT
        if elem == '!':
            return ''.join(('(?!', self.__make_word_regexp(mylist[1:]), ')'))
        # Implementing OR
        elif elem.find(' | ') != -1:
            listofors = elem.split(' | ')
            for o in listofors:
                in_bet = self.__is_inbetween(listofors, o)

                if o:
                    o = self.__make_not_expr(o)
                    if in_bet:
                        s = ''.join((s, '|', self._wordstr, o, '.*'))
                    else:
                        s = ''.join((s, self._wordstr, o, '.*'))

        # Implementing AND
        elif elem.find(' & ') != -1:
            listofands = elem.split(' & ')

            for a in listofands:
                if a:
                    a = self.__make_not_expr(a)                   
                    s = ''.join((s, self._wordstr, a, '.*'))

        else:
            if elem:
                elem = self.__make_not_expr(elem)             
                s = ''.join((self._wordstr, elem, '.*'))

        if eor:
            return s
        else:
            return ''.join((s, self.__make_word_regexp(mylist[1:])))


    def clean_up(self):
        """ Purge data for a project by cleaning up
        lists, dictionaries and resetting other member items"""

        # Reset lists
        self._links = []
        self._sourceurls = []
        self._filter = []
        self._extservers = []
        self._extdirs = []
        self._robocache = []
        # Reset dicts
        self._robots.clear()
        
class JunkFilter(object):
    """ Junk filter class. Filter out junk urls such
    as ads, banners, flash files etc """

    # Domain specific blocking - List courtesy
    # junkbuster proxy.
    block_domains =[ '1ad.prolinks.de',
                     '1st-fuss.com',
                     '247media.com',
                     'admaximize.com',
                     'adbureau.net',
                     'adsolution.de',
                     'adwisdom.com',
                     'advertising.com',
                     'atwola.com',
                     'aladin.de',
                     'annonce.insite.dk',
                     'a.tribalfusion.com',                           
                     'avenuea.com',
                     'bannercommunity.de',
                     'banerswap.com',
                     'bizad.nikkeibp.co.jp',
                     'bluestreak.com',
                     'bs.gsanet.com',
                     'cash-for-clicks.de',
                     'cashformel.com',                           
                     'cash4banner.de',
                     'cgi.tietovalta.fi',
                     'cgicounter.puretec.de',
                     'click-fr.com',
                     'click.egroups.com',
                     'commonwealth.riddler.com',
                     'comtrack.comclick.com',
                     'customad.cnn.com',
                     'cybereps.com:8000',
                     'cyberclick.net',
                     'dino.mainz.ibm.de',
                     'dinoadserver1.roka.net',
                     'disneystoreaffiliates.com',
                     'dn.adzerver.com',
                     'doubleclick.net',
                     'ds.austriaonline.at',
                     'einets.com',
                     'emap.admedia.net',
                     'eu-adcenter.net',
                     'eurosponser.de',
                     'fastcounter.linkexchange.com',
                     'findcommerce.com',
                     'flycast.com',
                     'focalink.com',
                     'fp.buy.com',
                     'globaltrack.com',
                     'globaltrak.net',
                     'gsanet.com',                           
                     'hitbox.com',
                     'hurra.de',
                     'hyperbanner.net',
                     'iadnet.com',
                     'image.click2net.com',
                     'image.linkexchange.com',
                     'imageserv.adtech.de',
                     'imagine-inc.com',
                     'img.getstats.com',
                     'img.web.de',
                     'imgis.com',
                     'james.adbutler.de',
                     'jmcms.cydoor.com',
                     'leader.linkexchange.com',
                     'linkexchange.com',
                     'link4ads.com',
                     'link4link.com',
                     'linktrader.com',
                     'media.fastclick.net',
                     'media.interadnet.com',
                     'media.priceline.com',
                     'mediaplex.com',
                     'members.sexroulette.com',
                     'newsads.cmpnet.com',
                     'ngadcenter.net',
                     'nol.at:81',
                     'nrsite.com',
                     'offers.egroups.com',
                     'omdispatch.co.uk',
                     'orientserve.com',
                     'pagecount.com',
                     'preferences.com',
                     'promotions.yahoo.com',
                     'pub.chez.com',
                     'pub.nomade.fr',
                     'qa.ecoupons.com',
                     'qkimg.net',
                     'resource-marketing.com',
                     'revenue.infi.net',
                     'sam.songline.com',
                     'sally.songline.com',
                     'sextracker.com',
                     'smartage.com',
                     'smartclicks.com',
                     'spinbox1.filez.com',
                     'spinbox.versiontracker.com',
                     'stat.onestat.com',
                     'stats.surfaid.ihost.com',
                     'stats.webtrendslive.com',
                     'swiftad.com',
                     'tm.intervu.net',
                     'tracker.tradedoubler.com',
                     'ultra.multimania.com',
                     'ultra1.socomm.net',
                     'uproar.com',
                     'usads.imdb.com',
                     'valueclick.com',
                     'valueclick.net',
                     'victory.cnn.com',
                     'videoserver.kpix.com',
                     'view.atdmt.com',
                     'webcounter.goweb.de',
                     'websitesponser.de',
                     'werbung.guj.de',
                     'wvolante.com',
                     'www.ad-up.com',
                     'www.adclub.net',
                     'www.americanpassage.com',
                     'www.bannerland.de',
                     'www.bannermania.nom.pl',
                     'www.bizlink.ru',
                     'www.cash4banner.com',                           
                     'www.clickagents.com',
                     'www.clickthrough.ca',
                     'www.commision-junction.com',
                     'www.eads.com',
                     'www.flashbanner.no',                           
                     'www.mediashower.com',
                     'www.popupad.net',                           
                     'www.smartadserver.com',                           
                     'www.smartclicks.com:81',
                     'www.spinbox.com',
                     'www.sponsorpool.net',
                     'www.ugo.net',
                     'www.valueclick.com',
                     'www.virtual-hideout.net',
                     'www.web-stat.com',
                     'www.webpeep.com',
                     'www.zserver.com',
                     'www3.exn.net:80',
                     'xb.xoom.com',
                     'yimg.com' ]

    # Common block patterns. These are created
    # in the Python regular expression syntax.
    # Original list courtesy junkbuster proxy.
    block_patterns = [ r'/*.*/(.*[-_.])?ads?[0-9]?(/|[-_.].*|\.(gif|jpe?g))',
                       r'/*.*/(.*[-_.])?count(er)?(\.cgi|\.dll|\.exe|[?/])',
                       r'/*.*/(.*[-_.].*)?maino(kset|nta|s).*(/|\.(gif|html?|jpe?g|png))',
                       r'/*.*/(ilm(oitus)?|kampanja)(hallinta|kuvat?)(/|\.(gif|html?|jpe?g|png))',
                       r'/*.*/(ng)?adclient\.cgi',
                       r'/*.*/(plain|live|rotate)[-_.]?ads?/',
                       r'/*.*/(sponsor|banner)s?[0-9]?/',
                       r'/*.*/*preferences.com*',
                       r'/*.*/.*banner([-_]?[a-z0-9]+)?\.(gif|jpg)',
                       r'/*.*/.*bannr\.gif',
                       r'/*.*/.*counter\.pl',
                       r'/*.*/.*pb_ihtml\.gif',
                       r'/*.*/Advertenties/',
                       r'/*.*/Image/BannerAdvertising/',
                       r'/*.*/[?]adserv',
                       r'/*.*/_?(plain|live)?ads?(-banners)?/',
                       r'/*.*/abanners/',
                       r'/*.*/ad(sdna_image|gifs?)/',
                       r'/*.*/ad(server|stream|juggler)\.(cgi|pl|dll|exe)',
                       r'/*.*/adbanner*',
                       r'/*.*/adfinity',
                       r'/*.*/adgraphic*',
                       r'/*.*/adimg/',
                       r'/*.*/adjuggler',
                       r'/*.*/adlib/server\.cgi',
                       r'/*.*/ads\\',
                       r'/*.*/adserver',
                       r'/*.*/adstream\.cgi',
                       r'/*.*/adv((er)?ts?|ertis(ing|ements?))?/',
                       r'/*.*/advanbar\.(gif|jpg)',
                       r'/*.*/advanbtn\.(gif|jpg)',
                       r'/*.*/advantage\.(gif|jpg)',
                       r'/*.*/amazon([a-zA-Z0-9]+)\.(gif|jpg)',
                       r'/*.*/ana2ad\.gif',
                       r'/*.*/anzei(gen)?/?',
                       r'/*.*/ban[-_]cgi/',
                       r'/*.*/banner_?ads/',
                       r'/*.*/banner_?anzeigen',
                       r'/*.*/bannerimage/',
                       r'/*.*/banners?/',
                       r'/*.*/banners?\.cgi/',
                       r'/*.*/bizgrphx/',
                       r'/*.*/biznetsmall\.(gif|jpg)',
                       r'/*.*/bnlogo.(gif|jpg)',
                       r'/*.*/buynow([a-zA-Z0-9]+)\.(gif|jpg)',
                       r'/*.*/cgi-bin/centralad/getimage',
                       r'/*.*/drwebster.gif',
                       r'/*.*/epipo\.(gif|jpg)',
                       r'/*.*/gsa_bs/gsa_bs.cmdl',
                       r'/*.*/images/addver\.gif',
                       r'/*.*/images/advert\.gif',
                       r'/*.*/images/marketing/.*\.(gif|jpe?g)',
                       r'/*.*/images/na/us/brand/',
                       r'/*.*/images/topics/topicgimp\.gif',
                       r'/*.*/phpAds/phpads.php',
                       r'/*.*/phpAds/viewbanner.php',
                       r'/*.*/place-ads',
                       r'/*.*/popupads/',
                       r'/*.*/promobar.*',
                       r'/*.*/publicite/',
                       r'/*.*/randomads/.*\.(gif|jpe?g)',
                       r'/*.*/reklaam/.*\.(gif|jpe?g)',
                       r'/*.*/reklama/.*\.(gif|jpe?g)',
                       r'/*.*/reklame/.*\.(gif|jpe?g)',
                       r'/*.*/servfu.pl',
                       r'/*.*/siteads/',
                       r'/*.*/smallad2\.gif',
                       r'/*.*/spin_html/',
                       r'/*.*/sponsor.*\.gif',
                       r'/*.*/sponsors?[0-9]?/',
                       r'/*.*/ucbandeimg/',
                       r'/*.*/utopiad\.(gif|jpg)',
                       r'/*.*/werb\..*',
                       r'/*.*/werbebanner/',
                       r'/*.*/werbung/.*\.(gif|jpe?g)',
                       r'/*ad.*.doubleclick.net',
                       r'/.*(ms)?backoff(ice)?.*\.(gif|jpe?g)',
                       r'/.*./Adverteerders/',
                       r'/.*/?FPCreated\.gif',
                       r'/.*/?va_banner.html',
                       r'/.*/adv\.',
                       r'/.*/advert[0-9]+\.jpg',
                       r'/.*/favicon\.ico',
                       r'/.*/ie_?(buttonlogo|static?|anim.*)?\.(gif|jpe?g)',
                       r'/.*/ie_horiz\.gif',
                       r'/.*/ie_logo\.gif',
                       r'/.*/ns4\.gif',
                       r'/.*/opera13\.gif',
                       r'/.*/opera35\.gif',
                       r'/.*/opera_b\.gif',
                       r'/.*/v3sban\.gif',
                       r'/.*Ad00\.gif',
                       r'/.*activex.*(gif|jpe?g)',
                       r'/.*add_active\.gif',
                       r'/.*addchannel\.gif',
                       r'/.*adddesktop\.gif',
                       r'/.*bann\.gif',
                       r'/.*barnes_logo\.gif',
                       r'/.*book.search\.gif',
                       r'/.*by/main\.gif',
                       r'/.*cnnpostopinionhome.\.gif',
                       r'/.*cnnstore\.gif',
                       r'/.*custom_feature\.gif',
                       r'/.*exc_ms\.gif',
                       r'/.*explore.anim.*gif',
                       r'/.*explorer?.(gif|jpe?g)',
                       r'/.*freeie\.(gif|jpe?g)',
                       r'/.*gutter117\.gif',
                       r'/.*ie4_animated\.gif',
                       r'/.*ie4get_animated\.gif',
                       r'/.*ie_sm\.(gif|jpe?g)',
                       r'/.*ieget\.gif',
                       r'/.*images/cnnfn_infoseek\.gif',
                       r'/.*images/pathfinder_btn2\.gif',
                       r'/.*img/gen/fosz_front_em_abc\.gif',
                       r'/.*img/promos/bnsearch\.gif',
                       r'/.*infoseek\.gif',
                       r'/.*logo_msnhm_*',
                       r'/.*mcsp2\.gif',
                       r'/.*microdell\.gif',
                       r'/.*msie(30)?\.(gif|jpe?g)',
                       r'/.*msn2\.gif',
                       r'/.*msnlogo\.(gif|jpe?g)',
                       r'/.*n_iemap\.gif',
                       r'/.*n_msnmap\.gif',
                       r'/.*navbars/nav_partner_logos\.gif',
                       r'/.*nbclogo\.gif',
                       r'/.*office97_ad1\.(gif|jpe?g)',
                       r'/.*pathnet.warner\.gif',
                       r'/.*pbbobansm\.(gif|jpe?g)',
                       r'/.*powrbybo\.(gif|jpe?g)',
                       r'/.*s_msn\.gif',
                       r'/.*secureit\.gif',
                       r'/.*sqlbans\.(gif|jpe?g)',
                       r'/BannerImages/'
                       r'/BarnesandNoble/images/bn.recommend.box.*',
                       r'/Media/Images/Adds/',
                       r'/SmartBanner/',
                       r'/US/AD/',
                       r'/_banner/',
                       r'/ad[-_]container/',
                       r'/adcycle.cgi',
                       r'/adcycle/',
                       r'/adgenius/',
                       r'/adimages/',
                       r'/adproof/',
                       r'/adserve/',
                       r'/affiliate_banners/',
                       r'/annonser?/',
                       r'/anz/pics/',
                       r'/autoads/',
                       r'/av/gifs/av_logo\.gif',
                       r'/av/gifs/av_map\.gif',
                       r'/av/gifs/new/ns\.gif',
                       r'/bando/',
                       r'/bannerad/',
                       r'/bannerfarm/',
                       r'/bin/getimage.cgi/...\?AD',
                       r'/cgi-bin/centralad/',
                       r'/cgi-bin/getimage.cgi/....\?GROUP=',
                       r'/cgi-bin/nph-adclick.exe/',
                       r'/cgi-bin/nph-load',
                       r'/cgi-bin/webad.dll/ad',
                       r'/cgi/banners.cgi',
                       r'/cwmail/acc\.gif',
                       r'/cwmail/amzn-bm1\.gif',
                       r'/db_area/banrgifs/',
                       r'/digitaljam/images/digital_ban\.gif',
                       r'/free2try/',
                       r'/gfx/bannerdir/',
                       r'/gif/buttons/banner_.*',
                       r'/gif/buttons/cd_shop_.*',
                       r'/gif/cd_shop/cd_shop_ani_.*',
                       r'/gif/teasere/',
                       r'/grafikk/annonse/',
                       r'/graphics/advert',
                       r'/graphics/defaultAd/',
                       r'/grf/annonif',
                       r'/hotstories/companies/images/companies_banner\.gif',
                       r'/htmlad/',
                       r'/image\.ng/AdType',
                       r'/image\.ng/transactionID',
                       r'/images/.*/.*_anim\.gif',
                       r'/images/adds/',
                       r'/images/getareal2\.gif',
                       r'/images/locallogo.gif',
                       r'/img/special/chatpromo\.gif',
                       r'/include/watermark/v2/',
                       r'/ip_img/.*\.(gif|jpe?g)',
                       r'/ltbs/cgi-bin/click.cgi',
                       r'/marketpl*/',
                       r'/markets/images/markets_banner\.gif',
                       r'/minibanners/',
                       r'/ows-img/bnoble\.gif',
                       r'/ows-img/nb_Infoseek\.gif',
                       r'/p/d/publicid',
                       r'/pics/amzn-b5\.gif',
                       r'/pics/getareal1\.gif',
                       r'/pics/gotlx1\.gif',
                       r'/promotions/',
                       r'/rotads/',
                       r'/rotations/',
                       r'/torget/jobline/.*\.gif'
                       r'/viewad/'
                       r'/we_ba/',
                       r'/werbung/',
                       r'/world-banners/',
                       r'/worldnet/ad\.cgi',
                       r'/zhp/auktion/img/' ]
                            

    def __init__(self):
        self.msg = '<No Error>'
        self.match = ''
        # Compile pattern list for performance
        self.patterns = map(re.compile, self.block_patterns)
        # Create base domains list from domains list
        self.base_domains = map(self.base_domain, self.block_domains)

    def reset_msg(self):
        self.msg = '<No Error>'

    def reset_match(self):
        self.msg = ''        
        
    def check(self, url_obj):
        """ Check whether the url is junk. Return
        True if the url is O.K (not junk) and False
        otherwise """

        self.reset_msg()
        self.reset_match()
        
        # Check domain first
        ret = self.__check_domain(url_obj)
        if not ret:
            return ret

        # Check pattern next
        return self.__check_pattern(url_obj)

    def base_domain(self, domain):

        if domain.count(".") > 1:
            strings = domain.split(".")
            return "".join((strings[-2], strings[-1]))
        else:
            return domain
            
    def __check_domain(self, url_obj):
        """ Check whether the url belongs to a junk
        domain. Return true if url is O.K (NOT a junk
        domain) and False otherwise """

        # Get base server of the domain with port
        base_domain_port = url_obj.get_base_domain_with_port()
        # Get domain with port
        domain_port = url_obj.get_domain_with_port()

        # First check for domain
        if domain_port in self.block_domains:
            self.msg = '<Found domain match>'
            return False
        # Then check for base domain
        else:
            if base_domain_port in self.base_domains:
                self.msg = '<Found base-domain match>'                
                return False

        return True

    def __check_pattern(self, url_obj):
        """ Check whether the url matches a junk pattern.
        Return true if url is O.K (not a junk pattern) and
        false otherwise """

        url = url_obj.get_full_url()

        indx=0
        for p in self.patterns:
            # Do a search, not match
            if p.search(url):
                self.msg = '<Found pattern match>'
                self.match = self.block_patterns[indx]
                return False
            
            indx += 1
            
        return True
            
    def get_error_msg(self):
        return self.msg

    def get_match(self):
        return self.match
    
if __name__=="__main__":
    # Test filter class
    filter = JunkFilter()
    
    # Violates, should return False
    # The first two are direct domain matches, the
    # next two are base domain matches.
    u = urlparser.HarvestManUrlParser("http://a.tribalfusion.com/images/1.gif")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    u = urlparser.HarvestManUrlParser("http://stats.webtrendslive.com/cgi-bin/stats.pl")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    u = urlparser.HarvestManUrlParser("http://stats.cyberclick.net/cgi-bin/stats.pl")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()    
    u = urlparser.HarvestManUrlParser("http://m.doubleclick.net/images/anim.gif")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    
    # The next are pattern matches
    u = urlparser.HarvestManUrlParser("http://www.foo.com/popupads/ad.gif")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    print '\tMatch=>',filter.get_match()
    u = urlparser.HarvestManUrlParser("http://www.foo.com/htmlad/1.html")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    print '\tMatch=>',filter.get_match()    
    u = urlparser.HarvestManUrlParser("http://www.foo.com/logos/nbclogo.gif")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    print '\tMatch=>',filter.get_match()    
    u = urlparser.HarvestManUrlParser("http://www.foo.com/bar/siteads/1.ad")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    print '\tMatch=>',filter.get_match()    
    u = urlparser.HarvestManUrlParser("http://www.foo.com/banners/world-banners/banner.gif")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    print '\tMatch=>',filter.get_match()
    u = urlparser.HarvestManUrlParser("http://ads.foo.com/")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    print '\tMatch=>',filter.get_match()    
    
    
    # This one should not match
    u = urlparser.HarvestManUrlParser("http://www.foo.com/doc/logo.gif")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()
    # This also...
    u = urlparser.HarvestManUrlParser("http://www.foo.org/bar/vodka/pattern.html")
    print filter.check(u),filter.get_error_msg(),'=>',u.get_full_url()    
