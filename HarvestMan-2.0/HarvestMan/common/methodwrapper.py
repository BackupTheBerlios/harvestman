# -- coding: latin-1
""" methodwrapper.py - Module which provides a meta-class level
implementation for method wrappers. The metaclasses provided here
specifically wrap pre_* and post_* methods defined in classes
and wrap them around the original method.

Any class which wants to auto-implement pre and post callbacks
need to set their __metaclass__ attribute to the type
MethodWrapperMetaClass. This has to be done at the time of
defining the class.

This module provides the function set_method_wrapper which
sets a given method as a pre or post callback method on a class.

This module is part of the HarvestMan program. For licensing
information see the file LICENSE.txt that is included in this distribution.

Author: Anand B Pillai <anand at harvestmanontheweb.com>
    
Created Anand B Pillai Feb 17 2007

Copyright (C) 2007 Anand B Pillai.
"""

__version__ = '2.0 b1'
__author__ = 'Anand B Pillai'

from new import function

class MethodWrapperBaseMetaClass(type):
    """ A base meta class for method wrappers """
    
    # This class allows wrapping pre_ and post_ callbacks
    # (methods) around a method. Original code courtesy
    # Eiffel method wrapper implementation in Python
    # subversion trunk @
    # http://svn.python.org/view/python/trunk/Demo/newmetaclasses/Eiffel.py
    
    def my_new(cls, *args, **kwargs):
        # Since this gets called at creation of every instance
        # we need to make sure that it gets done exactly once.
        if not getattr(cls, '__callbacks__',False):
            cls.convert_methods(cls.__dict__)
        return object.__new__(cls)
    
    def __init__(cls, name, bases, dct):
        super(MethodWrapperBaseMetaClass, cls).__init__(name, bases, dct)
        cls.__new__ = cls.my_new
        
    def convert_methods(cls, dict):
        """Replace functions in dict with MethodWrapper wrappers.

        The dict is modified in place.

        If a method ends in _pre or _post, it is removed from the dict
        regardless of whether there is a corresponding method.
        """
        # find methods with pre or post conditions
        methods = []
        for k, v in dict.iteritems():
            #if k.startswith('pre_') or k.startswith('post_'):
            #    print v
            #    assert isinstance(v, list)
            if isinstance(v, function):
                methods.append(k)
        for m in methods:
            pre = dict.get("pre_%s_callback" % m)
            post = dict.get("post_%s_callback" % m)
            if pre or post:
                setattr(cls, m, cls.make_wrapper_method(dict[m], pre, post))

        setattr(cls, '__callbacks__', True)
        
class MethodWrapperMetaClass(MethodWrapperBaseMetaClass):
    # an implementation of the "MethodWrapper" meta class that uses nested functions

    def make_wrapper_method(func, pre, post):
        def method(self, *args, **kwargs):
            if pre:
                for f in pre:
                    f(self, *args, **kwargs)
            x = func(self, *args, **kwargs)
            if post:
                for f in post:
                    f(self, x, *args, **kwargs)
            return x

        if func.__doc__:
            method.__doc__ = func.__doc__

        return method

    make_wrapper_method = staticmethod(make_wrapper_method)
    
def set_wrapper_method(klass, method, callback, where='post'):
    """ Set callback method 'callback' on the method with
    the given name 'method' on class 'klass'. If the last
    argument is 'post' the method is inserted as a post-callback.
    If the last argument is 'pre', it is inserted as a pre-callback.
    """
    
    # Note: 'method' is the method name, not the method object

    # Set callback
    attr = where + '_' + method + '_callback'
    l = getattr(klass, attr, None)
    if not l:
        setattr(klass, attr, [callback])
    else:
        l.append(callback)
        setattr(klass, attr, l)            

def test():
    class MyClass(object):
        __metaclass__ = MethodWrapperMetaClass
        
        def f(self):
            x = 10
            y = 20
            z = x + y
            print 'F called'
            return z

    def myfunc1(self):
        print 'Myfunc#1 called'

    def myfunc2(self, x):
        print 'Myfunc#2 called'

    def myfunc3(self, x):
        print 'Myfunc#3 called!'

    class MyClass2(MyClass):
        pass
    
    set_wrapper_method(MyClass, 'f', myfunc1, 'pre')    
    set_wrapper_method(MyClass, 'f', myfunc2, 'post')
    set_wrapper_method(MyClass, 'f', myfunc3, 'post')    

    c = MyClass()
    d = MyClass()
    e = MyClass()
    c.f()

    g = MyClass2()
    print 'hi'
    g.f()
    
if __name__=="__main__":
    test()
    
