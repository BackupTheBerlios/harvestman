""" Pyrex replacement for module urlparser.py -

Timing test results

1. Current version - Using script compar.py, the pyrex version
is around 70 usec faster than the Python version per func call.
Though this looks small, it can matter since a number of
HarvestManUrlParser objects are created during a single crawl
using HarvestMan.

This module can be probably improved further.

Created - Anand B Pillai         09/11/2005

"""

import re
import os
import mimetypes
import copy

from common import GetObject

__IDX__ = 0

# Testing flag
__TEST__= 0

class HarvestManUrlParserError(Exception):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return self.__str__()
    
    def __str__(self):
        return str(self.value)
    
cdef class HarvestManUrlParser:
    """ Pyrex extension of original HarvestManUrlParser
    class """

    # Class-level plain strings
    cdef char* URLSEP
    cdef char* PROTOSEP
    cdef char* DOTDOT
    cdef char* DOT
    cdef char* PORTSEP
    cdef char* BACKSLASH

    # Class-level Python objects
    cdef object protocol_map
    cdef object image_extns
    cdef object webpage_extns
    cdef object stylesheet_extns
    cdef object wspacere

    # Object-level plain strings
    # cdef char* typ

    # Object-level booleans,
    # declared as int

    cdef public int filelike
    cdef int defproto
    cdef int fatal
    cdef int starturl
    cdef int hasextn
    cdef int isrel
    cdef int isrels
    cdef int violatesrules
    cdef int rulescheckdone
    cdef int cgi
    
    # Object-level, plain integers
    cdef public int port
    cdef int index
    cdef int status
    cdef int rdepth
    cdef int generation
    cdef int priority
    cdef int rindex
    
    # Object-level Unicode strings
    # Since Pyrex does not support Unicode
    # we are force to declare them as
    # Python objects.
    cdef public object url
    cdef public object validfilename
    cdef public object domain
    cdef public object dirpath
    cdef public object rootdir
    cdef public object protocol
    
    cdef object origurl
    cdef object anchor
    cdef object filename
    cdef object lastpath
    cdef object rpath
    cdef object baseurl
    cdef object typ
    cdef object contentdict
    
    cdef __new__(cls):
        cls.URLSEP = "/"
        cls.PROTOSEP = "//"
        cls.DOTDOT = ".."
        cls.DOT = "."
        cls.PORTSEP = ":"
        cls.BACKSLASH= "\\"
        cls.protocol_map = { "http://" : 80,
                             "ftp://" : 21,
                             "https://" : 443,
                             "file://": 0
                             }

        # Popular image types file extensions
        cls.image_extns = ('.bmp', '.dib', '.dcx', '.emf', '.fpx', '.gif', '.img',
                           '.jp2', '.jpc', '.j2k', '.jpf', '.jpg', '.jpeg', '.jpe',
                           '.mng', '.pbm', '.pcd', '.pcx', '.pgm', '.png', '.ppm',
                           '.psd', '.ras', '.rgb', '.tga', '.tif', '.tiff', '.wbmp',
                           '.xbm', '.xpm')

        # Most common web page url file extensions
        # including dynamic server pages & cgi scripts.
        cls.webpage_extns = ('', '.htm', '.html', '.shtm', '.shtml', '.php',
                             '.php3','.php4','.asp', '.aspx', '.jsp','.psp','.pl',
                             '.cgi', '.stx', '.cfm', '.cfml', '.cms' )
        
        # Most common stylesheet url file extensions
        cls.stylesheet_extns = ( '.css', )        

        # Regular expression for matching
        # urls which contain white spaces
        cls.wspacere = re.compile(r'\w+\s+\w+')
        
    def __init__(self, url, urltype = 'normal', cgi=False, baseurl = None, rootdir = ""):
        
        if url[-1] == self.URLSEP:
            self.url = url[:-1]
        else:
            self.url = url
        
        # For saving original url
        # since self.url can get
        # modified
        self.origurl = url
        self.typ = urltype.lower()
        self.cgi = cgi
        self.anchor = ''
        self.index = 0
        self.rindex = 0
        self.filename = 'index.html'
        self.validfilename = 'index.html'
        self.lastpath = ''
        self.protocol = ''
        self.defproto = False
        # If the url is a file like url
        # this value will be true, if it is
        # a directory like url, this value will
        # be false.
        self.filelike = False
        # download status, a number indicating
        # whether this url was downloaded successfully
        # or not. 0 indicates a successful download, and
        # any number >0 indicates a failed download
        self.status = 0
        # Fatal status
        self.fatal = False
        # is starting url?
        self.starturl = False
        # Flag for files having extension
        self.hasextn = False
        # Relative path flags
        self.isrel = False
        # Relative to server?
        self.isrels = False
        self.port = 80
        self.domain = ''
        self.rpath = []
        # Recursion depth
        self.rdepth = 0
        # Content information for updating urls
        self.contentdict = {}
        # Url generation
        self.generation = 0
        # Url priority
        self.priority = 0
        # rules violation cache flags
        self.violatesrules = False
        self.rulescheckdone = False
        self.dirpath = []
        
        self.baseurl = {}
        # Base Url Dictionary
        if baseurl:
            if isinstance(baseurl, HarvestManUrlParser):
                self.baseurl = baseurl
            elif type(baseurl) is str:
                self.baseurl = HarvestManUrlParser(baseurl, 'normal', cgi, None, rootdir)
                      
        # Root directory
        if rootdir == '':
            if self.baseurl and self.baseurl.rootdir:
                self.rootdir = self.baseurl.rootdir
            else:
                self.rootdir = os.getcwd()
        else:
            self.rootdir = rootdir

        self.anchorcheck()
        self.resolveurl()        
        
    cdef anchorcheck(self):
        """ Checking for anchor tags and processing accordingly """

        if self.typ == 'anchor':
            if not self.baseurl:
                raise HarvestManUrlParserError, 'Base url should not be empty for anchor type url'
            
            index = self.url.rfind('#')
            if index != -1:
                newhref = self.url[:index]
                self.anchor = self.url[index:]
                if newhref:
                    self.url = newhref
                else:
                    self.url = self.baseurl.url
        else:
            pass        

    cdef resolve_protocol(self):
        """ Resolve the protocol of the url """

        url2 = self.url.lower()
        for proto in self.protocol_map:
            if url2.find(proto) != -1:
                self.protocol = proto
                self.port = self.protocol_map[proto]
                return True
        else:
            # Fix: Use regex for detecting WWW urls.
            # Check for WWW urls. These can begin
            # with a 'www.' or 'www' followed by
            # a single number (www1, www3 etc).
            wwwre = re.compile(r'^www(\d?)\.')

            if wwwre.match(url2):
                self.protocol = 'http://'
                self.url =  "".join((self.protocol, self.url))
                return True
            
            # Urls relative to server might
            # begin with a //. Then prefix the protocol
            # string to them.
            if self.url.find('//') == 0:
                # Pick protocol from base url
                if self.baseurl and self.baseurl.protocol:
                    self.protocol = self.baseurl.protocol
                else:
                    self.protocol = "http://"   
                self.url = "".join((self.protocol, self.url[2:]))
                return True

            # None of these
            # Protocol not resolved, so check
            # base url first, if not found, set
            # default protocol...
            if self.baseurl and self.baseurl.protocol:
                self.protocol = self.baseurl.protocol
            else:
                self.protocol = 'http://'

            self.defproto = True
        
            return False

    cdef resolveurl(self):
        """ Resolves the url finding out protocol, port, domain etc
        . Also resolves relative paths and builds a local file name
        for the url based on the root directory path """

        cdef int i

        if len(self.url)==0:
            raise HarvestManUrlParserError, 'Error: Zero Length Url'

        proto = self.resolve_protocol()

        paths = ''
        
        if not proto:
            # Could not resolve protocol, must be a relative url
            if not self.baseurl:
                raise HarvestManUrlParserError, 'Base url should not be empty for relative urls'

            # Set url-relative flag
            self.isrel = True
            # Is relative to server?
            if self.url[0] == '/':
                self.isrels = True
            
            # Split paths
            relpaths = self.url.split(self.URLSEP)

            # Build relative path by checking for "." and ".." strings
            self.rindex = 0
            # for ritem in relpaths:
            for i from 0 <= i < len(relpaths):
                ritem = relpaths[i]
                # If path item is ., .. or empty, increment
                # relpath index.
                if ritem in (self.DOT, self.DOTDOT, ""):
                    self.rindex = self.rindex + 1
                    # If path item is not empty, insert
                    # to relpaths list.
                    if ritem:
                        self.rpath.append(ritem)

                else:
                    # Otherwise, add the rest to paths
                    # with the separator
                    relpaths2 = relpaths[self.rindex:]
                    # for entry in relpaths[self.rindex:]:
                    for i from 0 <= i < len(relpaths2):
                        entry = relpaths2[i]
                        paths = "".join((paths, entry, self.URLSEP))

                    # Remove the last entry
                    paths = paths[:-1]
                    
                    # Again Trim if the relative path ends with /
                    # like href = /img/abc.gif/ 
                    if paths[-1] == '/':
                        paths = paths[:-1]
                    break
        else:
            # Absolute path, so 'paths' is the part of it
            # minus the protocol part.
            paths = self.url.replace(self.protocol, '')
            
        # Now compute local directory/file paths

        # For cgi paths, add a url separator at the end 
        if self.cgi:
            paths = "".join((paths, self.URLSEP))

        self.compute_dirpaths(paths)
        self.compute_domain_and_port()

    cdef compute_file_and_dir_paths(self):
        """ Compute file and directory paths """

        cdef int i
        if self.lastpath:
            dotindex = self.lastpath.find(self.DOT)
            if dotindex != -1:
                self.hasextn = True

            # If there is no extension or if there is
            # an extension which is occuring in the middle
            # of last path...
            if (dotindex == -1) or \
                ((dotindex >0) and (dotindex < (len(self.lastpath)-1))):
                self.filelike = True
                # Bug fix - Strip leading spaces & newlines
                self.validfilename =  self.make_valid_filename(self.lastpath.strip())
                self.filename = self.lastpath.strip()
                
                self.dirpath  = self.dirpath [:-1]
        else:
            if not self.isrel:
                self.dirpath  = self.dirpath [:-1]

        # Remove leading spaces & newlines from dirpath
        dirpath2 = []
        # for item in self.dirpath:
        for i from 0 <= i < len(self.dirpath):
            item = self.dirpath[i]
            dirpath2.append(item.strip())

        # Copy
        self.dirpath = dirpath2[:]
            
    cdef compute_dirpaths(self, path):
        """ Computer local file & directory paths for the url """

        cdef int i

        self.dirpath = path.split(self.URLSEP)
        self.lastpath = self.dirpath[-1]

        if self.isrel:
            # Construct file/dir names - This is valid only if the path
            # has more than one component - like www.python.org/doc .
            # Otherwise, the url is a plain domain
            # path like www.python.org .
            self.compute_file_and_dir_paths()

            # Interprets relative path
            # ../../. Nonsense relative paths are graciously ignored,
            self.rpath.reverse()
            if len(self.rpath) == 0 :
                if not self.rindex:
                    self.dirpath = self.baseurl.dirpath + self.dirpath
            else:
                pathstack = self.baseurl.dirpath[0:]

                # for ritem in self.rpath:
                for i from 0 <= i < len(self.rpath):
                    ritem = self.rpath[i]
                    
                    if ritem == self.DOT:
                        pathstack = self.baseurl.dirpath[0:]
                    elif ritem == self.DOTDOT:
                        if len(pathstack) !=0:
                            pathstack.pop()

                self.dirpath  = pathstack + self.dirpath 
        
            # Support for NONSENSE relative paths such as
            # g/../foo and g/./foo 
            # consider base = http:\\bar.com\bar1
            # then g/../foo => http:\\bar.com\bar1\..\foo => http:\\bar.com\foo
            # g/./foo  is utter nonsense and we feel free to ignore that.
            index = 0
            # for item in self.dirpath:
            for i from 0 <= i < len(self.dirpath):
                item = self.dirpath[i]
                if item in (self.DOT, self.DOTDOT):
                    self.dirpath.remove(item)
                if item == self.DOTDOT:
                    self.dirpath.remove(self.dirpath[index - 1])
                index = index + 1
        else:
            if len(self.dirpath) > 1:
                self.compute_file_and_dir_paths()
            
    cdef compute_domain_and_port(self):
        """ Computes url domain and port &
        re-computes if necessary """

        # Resolving the domain...
        
        # Domain is parent domain, if
        # url is relative :-)
        if self.isrel:
            self.domain = self.baseurl.domain
        else:
            # If not relative, then domain
            # if the first item of dirpath.
            self.domain=self.dirpath[0]
            self.dirpath = self.dirpath[1:]

        # Find out if the domain contains a port number
        # for example, server:8080
        dom = self.domain
        index = dom.find(self.PORTSEP)
        if index != -1:
            self.domain = dom[:index]
            # A bug here => needs to be fixed
            try:
                self.port   = int(dom[index+1:])
            except:
                pass

        # Now check if the base domain had a port specification (other than 80)
        # Then we need to use that port for all its children, otherwise
        # we can use default value.
        if self.baseurl and \
               self.baseurl.port != self.port and \
               self.baseurl.protocol != 'file://':
            self.port = self.baseurl.port

    cdef make_valid_filename(self, s):
        """ Replace junk characters to create a valid
        filename """

        junks='?*"<>!:/\\'
        for x in iter(junks):
            s = s.replace(x, '')

        # replace '%20' with the space
        # character (generated by POST requests)
        s = s.replace('%20', ' ')
        # replace %7E with ~
        s = s.replace('%7E', '~')
        # replace %2B with +
        s = s.replace('%2B', '+')
        
        return s

    cdef make_valid_url(self, url):
        """ Make a valid url """

        # Replace spaces between words
        # with '%20'.
        # For example http://www.foo.com/bar/this file.html
        # Fix: Use regex instead of blind
        # replacement.
        if self.wspacere.search(url):
            url = re.sub(r'\s', '%20', url)
            
        return url

    # ============ Begin - Is (Boolean Get) Methods =========== #
    def is_filename_url(self):
        """ Return whether this is file name url """

        # A directory url is something like http://www.python.org
        # which points to the <index.html> file inside the www.python.org
        # directory.A file name url is a url that points to an actual
        # file like http://www.python.org/doc/current/tut/tut.html

        return self.filelike

    def is_cgi(self):
        """ Check whether this url is a cgi (dynamic/form) link """

        return self.cgi

    def is_relative_path(self):
        """ Return whether the original url was a relative one """

        return self.isrel

    def is_relative_to_server(self):
        """ Return whether the original url was relative to the server """
        
        return self.isrels

    def is_image(self):
        """ Find out by filename extension if the file is an image """

        if self.typ == 'image':
            return True
        elif self.typ == 'normal':
            if self.validfilename:
                extn = ((os.path.splitext(self.validfilename))[1]).lower()
                if extn in self.image_extns:
                    return True
             
        return False
            
    def is_webpage(self):
        """ Find out by filename extension if the file <filename>
        is an html or html-like (server-side dynamic html files)
        file, or a candidate for one """

        # Note: right now we treat dynamic server-side scripts namely
        # php, psp, asp, pl, jsp, and cgi as possible html candidates, though
        # actually they might be generating non-html content (like dynamic
        # images.)
        if self.typ in ('webpage', 'base'):
            return True
        elif self.typ == 'normal':
            if self.validfilename:
                extn = ((os.path.splitext(self.validfilename))[1]).lower()
                if extn in self.webpage_extns:
                    return True
             
        return False

    def is_stylesheet(self):
        """ Find out whether the url is a style sheet type """

        if self.typ == 'stylesheet':
            return True
        elif self.typ == 'normal':
            if self.validfilename:
                extn = ((os.path.splitext(self.validfilename))[1]).lower()
                if extn in self.stylesheet_extns:
                    return True
             
        return False

    def is_equal(self, url):
        """ Find whether the passed url matches
        my url """

        # Try 2 tests, one straightforward
        # other with a "/" appended at the end
        myurl = self.get_full_url()
        if url==myurl:
            return True
        else:
            myurl = myurl + self.URLSEP
            if url==myurl:
                return True

        return False
        
    # ============ End - Is (Boolean Get) Methods =========== #  
    # ============ Begin - General Get Methods ============== #
    def get_url_content_info(self):
        """ Get the url content information """
        
        return self.contentdict
    
    def get_anchor(self):
        """ Return the anchor tag of this url """

        return self.anchor

    def get_anchor_url(self):
        """ Get the anchor url, if this url is an anchor type """

        return "".join((self.get_full_url(), self.anchor))

    def get_generation(self):
        """ Return the generation of this url """
        
        return self.generation    

    def get_priority(self):
        """ Get the priority for this url """

        return self.priority

    def get_download_status(self):
        """ Return the download status for this url """

        return self.status

    def get_type(self):
        """ Return the type of this url as a string """
        
        return self.typ

    def get_base_urlobject(self):
        """ Return the base url object of this url """
        
        return self.baseurl

    def get_url_directory(self):
        """ Return the directory path (url minus its filename if any) of the
        url """

        cdef int i
        # get the directory path of the url
        fulldom = self.get_full_domain()
        urldir = fulldom

        if self.dirpath:
            dirpath2 = []
            # for x in self.dirpath:
            for i from 0 <= i < len(self.dirpath):
                x = self.dirpath[i]
                dirpath2.append(x+'/')
                
            newpath = "".join((self.URLSEP, "".join(dirpath2)))
            urldir = "".join((fulldom, newpath))

        return urldir

    def get_url_directory_sans_domain(self):
        """ Return url directory minus the domain """

        cdef int i
        # New function in 1.4.1
        urldir = ''
        
        if self.dirpath:
            dirpath2 = []
            # for x in self.dirpath:
            for i from 0 <= i < len(self.dirpath):
                x = self.dirpath[i]
                dirpath2.append(x+'/')            
            urldir = "".join((self.URLSEP, "".join(dirpath2)))

        return urldir        
        
    def get_url(self):
        """ Return the url of this object """
        
        return self.url

    def get_original_url(self):
        """ Return the original url of this object """
        
        return self.origurl
    
    def get_full_url(self, intranet=0):
        """ Return the full url path of this url object after
        resolving relative paths, filenames etc """

        cdef int i
        
        rval = self.get_full_domain_with_port(intranet)
        if self.dirpath:
            dirpath2 = []
            # for x in self.dirpath:
            for i from 0 <= i < len(self.dirpath):
                x = self.dirpath[i]
                if x and not x[-1] == self.URLSEP:
                    dirpath2.append(x + self.URLSEP)
                    
            newpath = "".join(dirpath2)
            rval = "".join((rval, self.URLSEP, newpath))
            
        if rval[-1] != self.URLSEP:
            rval = rval + self.URLSEP

        if self.filelike:
            rval = "".join((rval, self.filename))
            
        return self.make_valid_url(rval)

    def get_full_url_sans_port(self):
        """ Return absolute url without the port number """

        cdef int i
        
        rval = self.get_full_domain()
        if self.dirpath:
            dirpath2 = []
            # for x in self.dirpath:
            for i from 0 <= i < len(self.dirpath):
                x = self.dirpath[i]
                dirpath2.append(x + '/')
                
            newpath = "".join(dirpath2)
            rval = "".join((rval, self.URLSEP, newpath))

        if rval[-1] != self.URLSEP:
            rval = rval + self.URLSEP

        if self.filelike:
            rval = "".join((rval, self.filename))

        return self.make_valid_url(rval)

    def get_port_number(self):
        """ Return the port number of this url """

        # 80 -> http urls
        return self.port

    def get_relative_url(self):
        """ Return relative path of url w.r.t the domain """

        cdef int i
        
        newpath=""
        if self.dirpath:
            dirpath2 = []
            # for x in self.dirpath:
            for i from 0 <= i < len(self.dirpath):
                x = self.dirpath[i]
                dirpath2.append(x+'/')
                
            newpath =  "".join(("/", "".join(dirpath2)))

        if self.filelike:
            newpath = "".join((newpath, self.filename))
            
        return self.make_valid_url(newpath)

    def get_base_domain(self):
        """ Return the base domain for this url object """

        # Explanation: Base domain is the domain
        # at the root of a given domain. For example
        # base domain of stats.foo.com is foo.com.
        # If there is no subdomain, this will be
        # the same as the domain itself.

        # If the server name is of the form say bar.foo.com
        # or vodka.bar.foo.com, i.e there are more than one
        # '.' in the name, then we need to return the
        # last string containing a dot in the middle.

        # Get domain
        domain = self.domain
        
        if domain.count('.') > 1:
            dotstrings = domain.split('.')
            # now the list is of the form => [vodka, bar, foo, com]

            # Return the last two items added with a '.'
            # in between
            return "".join((dotstrings[-2], ".", dotstrings[-1]))
        else:
            # The server is of the form foo.com or just "foo"
            # so return it straight away
            return domain

    def get_base_domain_with_port(self, intranet=0):
        """ Return the base domain (server) with port number
        appended to it, if the port number is not the
        default for the current protocol """
        
        if intranet or ((self.protocol == 'http://' and int(self.port) != 80) \
                        or (self.protocol == 'https://' and int(self.port) != 443) \
                        or (self.protocol == 'ftp://' and int(self.port) != 21)):
            return self.get_base_domain() + ':' + str(self.port)
        else:
            return self.get_base_domain()
        
    def get_domain(self):
        """ Return the domain (server) for this url object """
        
        return self.domain

    def get_full_domain(self):
        """ Return the full domain (protocol + domain) for this url object """
        
        return self.protocol + self.domain

    def get_full_domain_with_port(self, intranet=0):
        """ Return the domain (server) with port number
        appended to it, if the port number is not the
        default for the current protocol """

        if intranet or ((self.protocol == 'http://' and int(self.port) != 80) \
                        or (self.protocol == 'https://' and int(self.port) != 443) \
                        or (self.protocol == 'ftp://' and int(self.port) != 21)):
            return self.get_full_domain() + ':' + str(self.port)
        else:
            return self.get_full_domain()

    def get_domain_with_port(self, intranet=0):
        """ Return the domain (server) with port number
        appended to it, if the port number is not the
        default for the current protocol """

        if intranet or ((self.protocol == 'http://' and self.port != 80) \
                        or (self.protocol == 'https://' and self.port != 443) \
                        or (self.protocol == 'ftp://' and self.port != 21)):
            return self.domain + ':' + str(self.port)
        else:
            return self.domain

    def get_full_filename(self):
        """ Return the full filename of this url on the disk.
        This is created w.r.t the local directory where we save
        the url data """

        if not __TEST__:
            cfg = GetObject('config')
            if cfg.rawsave:
                return self.get_filename()
            else:
                return os.path.join(self.get_local_directory(), self.get_filename())
        else:
            return os.path.join(self.get_local_directory(), self.get_filename())            

    def get_filename(self):
        """ Return the filenam of this url on the disk. """

        # NOTE: This is just the filename, not the absolute filename path
        if self.cgi or not self.filelike:
            self.validfilename = 'index.html'
            
        return self.validfilename

    def get_relative_filename(self, filename=''):

        cdef int i
        # NOTE: Rewrote this method completely
        # on Nov 18 for 1.4 b2.
        
        # If no file name given, file name
        # is the file name of the parent url
        if not filename:
            if self.baseurl:
                filename = self.baseurl.get_full_filename()

        # Still filename is NULL,
        # return my absolute path
        if not filename:
            return self.get_full_filename()
        
        # Get directory of 'filename'
        diry = os.path.dirname(filename)
        if diry[-1] != os.sep:
            diry = diry + os.sep
            
        # Get my filename
        myfilename = self.get_full_filename()
        # If the base domains are different, we
        # cannot find a relative path, so return
        # my filename itself.
        bdomain = self.baseurl.get_domain()
        mydomain = self.get_domain()

        if mydomain != bdomain:
            return myfilename

        # If both filenames are the same,
        # return just the filename.
        if myfilename==filename:
            return self.get_filename()
        
        # Get common prefix of my file name &
        # other file name.
        prefix = os.path.commonprefix([myfilename, filename])
        relfilename = ''
        
        if prefix:
            if not os.path.exists(prefix):
                prefix = os.path.dirname(prefix)
            
            if prefix[-1] != os.sep:
                prefix = prefix + os.sep

            # If prefix is the name of the project
            # directory, both files have no
            # common component.
            try:
                if os.path.samepath(prefix,self.rootdir):
                    return myfilename
            except:
                if prefix==self.rootdir:
                    return myfilename
            
            # If my directory is a subdirectory of
            # 'dir', then prefix should be the same as
            # 'dir'.
            sub=False

            # To test 'sub-directoriness', check
            # whether dir is wholly contained in
            # prefix. 
            prefix2 = os.path.commonprefix([diry,prefix])
            if prefix2[-1] != os.sep:
                prefix2 = prefix2 + os.sep
            
            # os.path.samepath is not avlbl in all
            # platforms.
            try:
                if os.path.samepath(diry, prefix2):
                    sub=True
            except:
                if diry==prefix2:
                    sub=True

            # If I am in a sub-directory, relative
            # path is my filename minus the common
            # path.
            if sub:
                relfilename = myfilename.replace(prefix2, '')
                return relfilename
            else:
                # If I am not in sub-directory, then
                # we need to get the relative path.
                dirwithoutprefix = diry.replace(prefix, '')
                filewithoutprefix = myfilename.replace(prefix, '')
                relfilename = filewithoutprefix
                    
                paths = dirwithoutprefix.split(os.sep)
                # for item in paths:
                for i from 0 <= i < len(paths):
                    item = paths[i]
                    if item:
                        relfilename = "".join(('..', os.sep, relfilename))

                return relfilename
        else:
            # If there is no common prefix, then
            # it means me and the passed filename
            # have no common paths, so return my
            # full path.
            return myfilename
            
    def get_relative_depth(self, hu, mode=0):
        """ Get relative depth of current url object vs passed url object.
        Return a postive integer if successful and -1 on failure """

        # Fixed 2 bugs on 22/7/2003
        # 1 => passing arguments to find function in wrong order
        # 2 => Since we allow the notion of zero depth, even zero
        # value of depth should be returned.

        # This mode checks for depth based on a directory path
        # This check is valid only if dir2 is a sub-directory of dir1
        dir1=self.get_url_directory()
        dir2=hu.get_url_directory()

        # spit off the protocol from directories
        dir1 = dir1.replace(self.protocol, '')
        dir2 = dir2.replace(self.protocol, '')      

        # Append a '/' to the dirpath if not already present
        if dir1[-1] != '/': dir1 = dir1 + '/'
        if dir2[-1] != '/': dir2 = dir2 + '/'

        if mode==0:
            # check if dir2 is present in dir1
            # bug: we were passing arguments to the find function
            # in the wrong order.
            if dir1.find(dir2) != -1:
                # we need to check for depth only if the above condition is true.
                l1=dir1.split('/')
                l2=dir2.split('/')
                if l1 and l2:
                    diff=len(l1) - len(l2)
                    if diff>=0: return diff

            return -1
        # This mode checks for depth based on the base server(domain).
        # This check is valid only if dir1 and dir2 belong to the same
        # base server (checked by name)
        elif mode==1:
            if self.domain == hu.domain:
                # we need to check for depth only if the above condition is true.
                l1=dir1.split('/')
                l2=dir2.split('/')
                if l1 and l2:
                    diff=len(l1) - len(l2)
                    if diff>=0: return diff
            return -1

        # This check is done for the current url against current base server (domain)
        # i.e, this mode does not use the argument 'hu'
        elif mode==2:
            dir2 = self.domain
            if dir2[-1] != '/':
                dir2 = dir2 + '/'

            # we need to check for depth only if the above condition is true.
            l1=dir1.split('/')
            l2=dir2.split('/')
            if l1 and l2:
                diff=len(l1) - len(l2)
                if diff>=0: return diff
            return -1

        return -1

    def get_root_dir(self):
        """ Return root directory """
        
        return self.rootdir
    
    def get_local_directory(self):
        """ Return the local directory path of this url w.r.t
        the directory on the disk where we save the files of this url """

        cdef int i
        # Gives Local Direcory path equivalent to URL Path in server
        # Could be used to cache HTML pages to disk
        rval = os.path.join(self.rootdir, self.domain)

        # for diry in self.dirpath:
        for i from 0 <= i < len(self.dirpath):
            diry = self.dirpath[i]
            if not diry: continue
            rval = os.path.abspath( os.path.join(rval, self.make_valid_filename(diry)))

        return os.path.normpath(rval)

    # ============ Begin - Set Methods =========== #
    def set_directory_url(self):
        """ Set this as a directory url """

        self.filelike = False
        if not self.dirpath or \
               (self.dirpath and self.dirpath[-1] != self.lastpath):
            self.dirpath.append(self.lastpath)
        self.validfilename = 'index.html'
        
    def set_url_content_info(self, headers):
        """ This function sets the url content information of this
        url. It is a convenient function which can be used by connectors
        to store url content information """

        if headers:
            self.contentdict = copy.deepcopy(headers)

    def violates_rules(self):
        """ Check if this url violates existing download rules """

        if not self.rulescheckdone:
            self.violatesrules = GetObject('ruleschecker').violates_basic_rules(self)
            self.rulescheckdone = True

        return self.violatesrules

    def manage_content_type(self, content_type):
        """ This function gets called from connector modules
        connect method, after retrieving information about
        a url. This function can manage the content type of
        the url object if there are any differences between
        the assumed type and the returned type """

        # Guess extension of type
        extn = mimetypes.guess_extension(content_type)
        if extn:
            if extn in self.webpage_extns:
                self.typ = 'webpage'
            elif extn in self.image_extns:
                self.typ = 'image'
            elif extn in self.stylesheet_extns:
                self.typ = 'stylesheet'
            else:
                self.typ = 'file'
        else:
            # Do some generic tests
            klass, typ = content_type.split('/')
            if klass == 'image':
                self.typ = 'image'
            elif typ == 'html':
                self.typ = 'webpage'

    def set_index(self):
        global __IDX__
        __IDX__ = __IDX__ + 1
        self.index = __IDX__

    # ============ End - Set Methods =========== #
        
def main():
    # Test code
    global __TEST__
    __TEST__ = 1
    
    hulist = [HarvestManUrlParser('http://www.yahoo.com/photos/my photo.gif'),
              HarvestManUrlParser('http://www.rediff.com:80/r/r/tn2/2003/jun/25usfed.htm'),
              HarvestManUrlParser('http://cwc2003.rediffblogs.com'),
              HarvestManUrlParser('/sports/2003/jun/25beck1.htm',
                                  'normal', 0, 'http://www.rediff.com', ''),
              HarvestManUrlParser('ftp://ftp.gnu.org/pub/lpf.README'),
              HarvestManUrlParser('http://www.python.org/doc/2.3b2/'),
              HarvestManUrlParser('//images.sourceforge.net/div.png',
                                  'image', 0, 'http://sourceforge.net', ''),
              HarvestManUrlParser('http://pyro.sourceforge.net/manual/LICENSE'),
              HarvestManUrlParser('python/test.htm', 'normal', 0,
                                  'http://www.foo.com/bar', ''),
              HarvestManUrlParser('/python/test.css', 'normal',
                                  0, 'http://www.foo.com/bar/vodka/test.htm', ''),
              HarvestManUrlParser('/visuals/standard.css', 'normal', 0,
                                  'http://www.garshol.priv.no/download/text/perl.html',
                                  'd:/websites'),
              HarvestManUrlParser('www.fnorb.org/index.html', 'normal',
                                  0, 'http://pyro.sourceforge.net',
                                  'd:/websites'),
              HarvestManUrlParser('http://profigure.sourceforge.net/index.html',
                                  'normal', 0, 'http://pyro.sourceforge.net',
                                  'd:/websites'),
              HarvestManUrlParser('#anchor', 'anchor', 0, 
                                  'http://www.foo.com/bar/index.html',
                                  'd:/websites'),
              HarvestManUrlParser('../icons/up.png', 'image', 0,
                                  'http://www.python.org/doc/current/tut/node2.html',
                                  ''),
              HarvestManUrlParser('../eway/library/getmessage.asp?objectid=27015&moduleid=160',
                                  'normal',0,'http://www.eidsvoll.kommune.no/eway/library/getmessage.asp?objectid=27015&moduleid=160')
                                  
              ]



    for hu in hulist:
        print
        print 'Full filename = ', hu.get_full_filename()
        print 'Valid filename = ', hu.validfilename
        print 'Local Filename  = ', hu.get_filename()
        print 'Is relative path = ', hu.is_relative_path()
        print 'Full domain = ', hu.get_full_domain()
        print 'Domain      = ', hu.domain
        print 'Local Url directory = ', hu.get_url_directory_sans_domain()
        print 'Absolute Url = ', hu.get_full_url()
        print 'Absolute Url Without Port = ', hu.get_full_url_sans_port()
        print 'Local Directory = ', hu.get_local_directory()
        print 'Is filename parsed = ', hu.filelike
        print 'Path rel to domain = ', hu.get_relative_url()
        print 'Connection Port = ', hu.get_port_number()
        print 'Domain with port = ', hu.get_full_domain_with_port()
        print 'Relative filename = ', hu.get_relative_filename()
        print 'Anchor url     = ', hu.get_anchor_url()
        print 'Anchor tag     = ', hu.get_anchor()

