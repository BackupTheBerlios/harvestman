# -- coding: latin-1
"""
urlcollections.py - Module which defines URL collection
and context classes.

URL collection classes allow a programmer to
create collections (aggregations) of URL objects
with respect to certain contexts. This allows to
treat URL objects belonging to the collection (and hence
the context) as a single unit allowing you to write
code based on the context rather than based on
the URL.

Examples of contexts include stylesheet context
where a web-page and its CSS files forms part of
this context. Other examples are frame contexts, where
a context is associated to all frame URLs originating
from a web-page and page contexts, which basically
associates all URLs in page to the page URL.

This module is part of the HarvestMan program.
For licensing information see the file LICENSE.txt that
is included in this distribution.

Author Anand B Pillai <abpillai at gmail dot com>

Created Anand B Pillai April 17 2007 Based on inputs from
                                     the EIAO project.


Copyright (C) 2007, Anand B Pillai.

"""

import urltypes

class HarvestManUrlCollectionException(Exception):
    """ Exception class for collections """

    pass

class HarvestManUrlContext(object):
    """ This class defines the base URL context type for HarvestMan """

    # Name for the context
    name = 'BASE_URL_CONTEXT'
    # Description for the context
    description = 'Base type for URL contexts'
    # Source URL type for the context
    sourcetype = urltypes.TYPE_ANY
    # Bag URL types for the context
    bagurltype = urltypes.TYPE_ANY
    
class HarvestManPageContext(HarvestManUrlContext):
    """ Page context class. This context ties a webpage URL
    with its child URLs """

    # Name for the context
    name = 'PAGE_URL_CONTEXT'
    # Description for the context
    description = 'Context type associating a page to its children'
    # Source URL type for the context
    sourcetype = urltypes.TYPE_WEBPAGE
    # Bag URL types for the context
    bagurltype = urltypes.TYPE_ANY
    
class HarvestManFrameContext(HarvestManPageContext):
    """ Frame context. This context ties a frameset URL
    to the frame URLs """
    
    # Name for the context
    name = 'FRAME_URL_CONTEXT'
    # Description of the context
    description = 'Context for tying a frameset URL to its frame URLs'
    # Source URL type for the context
    sourcetype = urltypes.TYPE_FRAMESET
    # Bag URL types for the context
    bagurltype = urltypes.TYPE_FRAME

class HarvestManStyleContext(HarvestManPageContext):
    """ Style context. This context ties a webpage URL to its
    stylesheet (css) URLs """

    # Name for the context
    name = 'STYLE_URL_CONTEXT'
    # Description of the context
    description = 'Context for tying a webpage to its stylesheets'
    # Source URL type for the context
    sourcetype = urltypes.TYPE_WEBPAGE
    # Bag URL types for the context
    bagurltype = urltypes.TYPE_STYLESHEET


class HarvestManCSSContext(HarvestManPageContext):
    """ CSS context. This context ties a stylesheet URL to any
    URLs defined inside the stylesheet """

    # Name for the context
    name = 'CSS_URL_CONTEXT'
    # Description of the context
    description = 'Context for tying a stylesheet to its child URLs'
    # Source URL type for the context
    sourcetype = urltypes.TYPE_STYLESHEET
    # Bag URL types for the context
    bagurltype = urltypes.TYPE_ANY

class HarvestManCSS2Context(HarvestManPageContext):
    """ CSS2 context. This context ties a stylesheet URL to any
    other stylesheets imported in it """

    # Name for the context
    name = 'CSS2_URL_CONTEXT'
    # Description of the context
    description = 'Context for tying a stylesheet to any stylesheets imported in it'
    # Source URL type for the context
    sourcetype = urltypes.TYPE_STYLESHEET
    # Bag URL types for the context
    bagurltype = urltypes.TYPE_STYLESHEET     
    
class HarvestManUrlCollection(object):
    """ URL collection classes for HarvestMan """

    # This class is designed as a bag for HarvestManUrlParser
    # objects, tied to a context. The key attributes of this
    # class are a list of such url objects, a main URL
    # object from which the context originates (the 'source'
    # URL object) and a corresponding context.

    def __init__(self, source = None, context = HarvestManUrlContext):
        self._source = source
        self._context = context
        self._urls = []
        if self._source:
            if self._source.typ != self._context.sourcetype:
                raise HarvestManUrlCollectionException, 'Error: mismatch in context and source URL types!'


    def addURL(self, urlobj):
        """ Add a url object to the collection """

        # Check if the type of the urlobject matches the
        # bagurltype defined for this context. Here we
        # do a isA check since the url object's type can
        # be a specialized form (derived class) of the
        # bagurltype.
        
        if urlobj.typ.isA(self._context.bagurltype):
            self._urls.append(urlobj)
        else:
            raise HarvestManUrlCollectionException, 'Error: mismatch in context and bag URL types!'

    def removeURL(self, urlobj):
        """ Remove a url object from the collection """
        
        try:
            self._urls.remove(urlobj)
        except ValueError, e:
            pass


    def getURLs(self):
        """ Get list of URL objects """

        return self._urls

    def getURLContext(self):
        """ Get the URL context """

        return self._context


            
