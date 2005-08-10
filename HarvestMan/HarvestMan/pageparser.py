# -- coding: latin-1
""" HarvestManPageParser.py - Module to parse an html page and
    extract its links. This software is part of the
    HarvestMan program.

    Author: Anand B Pillai (anandpillai at letterboxes dot org).
    
    For licensing information see the file LICENSE.txt that
    is included in this distribution.

    Dependency
    ==========
    WebHTMLParser, string

    Jun 14 2004       Anand          1.3.9 release.
    May 14 2005       Anand          1.4.1 - Replaced parser
                                     with one derived from SGMLParser
                                     instead of htmlparser. Discontinued
                                     usage of HTML tidy.

                                     [Original code of SGMLParser derived
                                     parser, courtesy Leonardo of BeautifulSoup
                                     module]
                                     
"""

from sgmllib import SGMLParser
from common import *
import re

class CaselessDict(dict):

    def has_key(self, key):
        if key in self or key.lower() in self:
            return True
        return False
    
class harvestManSimpleParser(SGMLParser):
    """ This class contains our handler methods for HTML elements
    which can be used by various parsers """

    def __init__(self):
        self._handled = { 'a' : (('href', 'normal'), ('href', 'anchor')),
                          'base': (('href', 'base'),),
                          'frame': (('src', 'normal'),),
                          'img' : (('src', 'image'),),
                          'form' : (('action', 'form'),),
                          'link' : (('href', ''),),
                          'body' : (('background', 'image'),),
                          'script' : (('src', 'javascript'),),
                          'applet' : (('codebase', 'appletcodebase'), ('code', 'javaapplet'))
                        }        
        self.links = []
        self.images = []
        # Fix for <base href="..."> links
        self.base_href = False
        # Base url for above
        self.base = None
        # anchor links flag
        self._anchors = True
        SGMLParser.__init__(self)
        
    def save_anchors(self, value):
        """ Set the save anchor links flag """

        # Warning: If you set this to true, anchor links on
        # webpages will be saved as separate files.
        self._anchors = value

    def filter_link(self, link):
        """ Function to filter links, we decide here whether
        to handle certain kinds of links """

        if not link: return

        # ignore javascript links (From 1.2 version javascript
        # links of the form .js are fetched, but we still ignore
        # the actual javascript actions since there is no
        # javascript engine.)
        llink = link.lower()

        # Skip javascript, mailto, news and directory special tags.
        skip_re = re.compile(r'(javascript:)|(mailto:)|(news:)|(\?m=a)|(\?n=d)|(\?s=a)|(\?d=a)')

        # Skip query forms
        query_re = re.compile(r'[-.:_a-zA-Z0-9]*\?[-.:_a-zA-Z0-9]*=[-.a:_-zA-Z0-9]*')
        if skip_re.match(llink):
            return 1

        cfg = GetObject('config')
        if cfg.skipqueryforms and query_re.search(llink):
            return 1

        return 0

    def handle_anchor_links(self, link):
        """ Handle links of the form html#..."""

        # if anchor tag, then get rid of anchor #...
        # and only add the webpage link
        if not link: return

        self.links.append(('anchor', link))

        # No point in getting #anchor sort of links
        # since they point to anchors in the same page
        index = link.rfind('.html#')
        if index != -1:
            newhref = link[:(index + 5)]
            self.links.append(('normal', newhref))
            return 0
        else:
            index = link.rfind('.htm#')
            if index != -1:
                newhref = link[:(index + 4)]
                self.links.append(('normal', newhref))
            return 0

        return 1

    def unknown_starttag(self, tag, attrs):
        """ This method gives you the tag in the html
        page along with its attributes as a list of
        tuples """

        # We handle the following tags
        # a => hypertext links
        # img => image links
        # link => css/icon etc
        # form => cgi forms
        # body => for background images
        # frame => for redirects

        if not attrs: return
        #print attrs
        
        isBaseTag = not self.base and tag == 'base'

        if tag in self._handled:

            d = CaselessDict(attrs)
            _values = (self._handled[tag])

            link = ''

            for v in _values:
                key = v[0]
                typ = v[1]

                # If there is a <base href="..."> tag
                # set self.base_href
                if isBaseTag and key=='href':
                    self.base_href = True
                    try:
                        self.base = d[key]
                    except:
                        self.base_href = False
                        continue
                
                # if the link already has a value, skip
                # (except for applet tags)
                if tag != 'applet':
                    if link: continue

                if tag == 'link':
                    try:
                        typ = d['rel']
                    except KeyError:
                        pass

                try:
                    if tag != 'applet':
                        link = d[key]
                    else:
                        link += d[key]
                        if key == 'codebase':
                            if link:
                                if link[-1] != '/':
                                    link += '/'
                            continue                                

                except KeyError:
                    continue

                # see if this link is to be filtered
                if self.filter_link(link):
                    debug('Filtering link ', link)
                    continue

                # anchor links in a page should not be saved        
                index = link.find('#')
                if index != -1:
                    self.handle_anchor_links(link)
                else:
                    # append to private list of links
                    self.check_add_link(typ, link)

    def check_add_link(self, typ, link):
        """ To avoid adding duplicate links """

        f = False

        if typ == 'image':
            for k,v  in self.images:
                if v == link:
                    f = True
                    break

            if not f:
                # moredebug('Adding image ', link, typ)
                #print 'Adding image ', link, typ
                self.images.append((typ, link))
        else:
            for k,v in self.links:
                if v == link:
                    f = True
                    break

            if not f:
                # moredebug('Adding link ', link, typ)
                #print 'Adding link ', link, typ
                self.links.append((typ, link))

    def add_tag_info(self, taginfo):
        """ Add new tag information to this object.
        This can be used to change the behavior of this class
        at runtime by adding new tags """

        # The taginfo object should be a dictionary
        # of the form { tagtype : (elementname, elementype) }

        # egs: { 'body' : ('background', 'img) }
        if type(taginfo) != dict:
            raise AttributeError, "Attribute type mismatch, taginfo should be a dictionary!"

        # get the key of the dictionary
        key = (taginfo.keys())[0]
        if len(taginfo[key]) != 2:
            raise ValueError, 'Value mismatch, size of tag tuple should be 2'

        # get the value tuple
        tagelname, tageltype = taginfo[key]

        # see if this is an already existing tagtype
        if key in self._handled.keys:
            _values = self._handled[key]

            f=0
            for index in xrange(len(_values)):
                # if the elementname is also
                # the same, just replace it.
                v = _values[index]

                elname, eltype = v
                if elname == tagelname:
                    f=1
                    _values[index] = (tagelname, tageltype)
                    break

            # new element, add it to list
            if f==0: _values.append((tagelname, tageltype))
            return 0

        else:
            # new key, directly modify dictionary
            elements = []
            elements.append((tagelname, tageltype))
            self._handled[key] = elements 

    def reset(self):
        SGMLParser.reset(self)
        del self.links
        del self.images

        self.base = None
        self.links = []
        self.images = []
        self.base_href = False
        self.base_url = ''
        
    def base_url_defined(self):
        """ Return whether this url had a
        base url of the form <base href='...'>
        defined """

        return self.base_href

    def get_base_url(self):
        return self.base
    
if __name__=="__main__":
    Initialize()

    cfg = GetObject('config')
    cfg.verbosity = 5
    
    p=harvestManSimpleParser()
    p.feed(open('escher.html').read())
    pass





