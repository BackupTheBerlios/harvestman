# -- coding: latin-1
""" hooks.py - Module allowing developer extensions(plugins/callbacks)
    to HarvestMan. This module makes it possible to hook into/modify the
    execution flow of HarvestMan, making it easy to extend and customize
    it. This module is part of the HarvestMan program.

    Created by Anand B Pillai <abpillai at gmail dot com> Feb 1 07.

    Modified by Anand B Pillai Feb 17 2007 Completed callback implementation
                                           using metaclass methodwrappers.

   Copyright (C) 2007 Anand B Pillai.    
"""

__version__ = '1.5 b1'
__author__ = 'Anand B Pillai'

from common.singleton import Singleton
from common.methodwrapper import MethodWrapperMetaClass, set_wrapper_method

class HarvestManHooksException(Exception):
    """ Exception class for HarvestManHooks class """
    pass

class HarvestManHooks(Singleton):
    """ Class which manages pluggable hooks and callbacks for HarvestMan """
    
    supported_modules = ('crawler','harvestman', 'urlqueue', 'datamgr', 'connector')
    module_hooks = {}
    module_callbacks = {}
    
    def __init__(self):
        self.run_hooks = {}
        self.run_callbacks = {}
        
    def add_all_hooks(cls):

        for module in cls.supported_modules:
            # Get __hooks__ attribute from the module
            M = __import__(module)
            hooks = getattr(M, '__hooks__',{})
            # print hooks
            for hook in hooks.keys():
                cls.add_hook(module, hook)

        # print cls.module_hooks

    def add_all_callbacks(cls):

        for module in cls.supported_modules:
            # Get __hooks__ attribute from the module
            M = __import__(module)
            callbacks = getattr(M, '__callbacks__',{})
            # print hooks
            for cb in callbacks.keys():
                cls.add_callback(module, cb)
                
    def add_hook(cls, module, hook):
        """ Add a hook named 'hook' for module 'module' """

        l = cls.module_hooks.get(module)
        if l is None:
            cls.module_hooks[module] = [hook]
        else:
            l.append(hook)

    def add_callback(cls, module, callback):
        """ Add a callback named 'callback' for module 'module' """

        l = cls.module_callbacks.get(module)
        if l is None:
            cls.module_callbacks[module] = [callback]
        else:
            l.append(callback)            

    def get_hooks(cls, module):
        """ Return all hooks for module 'module' """

        return cls.module_hooks.get(module)

    def get_callbacks(cls, module):
        """ Return all callbacks for module 'module' """

        return cls.module_callbacks.get(module)    

    def get_all_hooks(cls):
        """ Return the hooks data structure """

        # Note this is a copy of the dictionary,
        # so modifying it will not have any impact
        # locally.
        return cls.module_hooks.copy()

    def get_all_callbacks(cls):
        """ Return the callbacks data structure """

        # Note this is a copy of the dictionary,
        # so modifying it will not have any impact
        # locally.
        return cls.module_callbacks.copy()    

    def set_hook_func(self, context, func):
        """ Set hook function 'func' for context 'context' """

        self.run_hooks[context] = func
        # Inject the given function in place of the original
        module, hook = context.split(':')
        # Load module and get the entry point
        M = __import__(module)
        orig_func = getattr(M, '__hooks__').get(hook)
        # Orig func is in the form class:function
        klassname, function = orig_func.split(':')
        if klassname:
            klass = getattr(M, klassname)
            # Replace function with the new one
            funcobj = getattr(klass, function)
            setattr(klass, function, func)
            # print getattr(klass, function)
        else:
            # No class perhaps. Directly override
            setattr(M, function, func)

        
    def set_callback_method(self, context, method, order='post'):
        """ Set callback method at context as the given
        method 'method'. The callback will be inserted after
        the original function call if order is 'post' and
        inserted before the original function call if order
        is 'pre' """

        self.run_callbacks[order + ':' + context] = method
        module, hook = context.split(':')
        # Load module and get the entry point
        M = __import__(module)
        orig_meth = getattr(M, '__callbacks__').get(hook)
        
        # Orig func is in the form class:function
        klassname, origmethod = orig_meth.split(':')
        if klassname:
            klass = getattr(M, klassname)
            # If klass does not define its __metaclass__ attribute
            # as MethodWrapperMetaClass, then we cannot do anything.
            if getattr(klass, '__metaclass__',None) != MethodWrapperMetaClass:
                raise HarvestManHooksException, 'Error: Cannot set callback on klass %s, __metaclass__ attribute is not set correctly!' % klassname
            
            # Insert new function which basicaly calls
            # new function before or after the original
            methobj = getattr(klass, origmethod)
            # Post call back function should take one extra argument
            # than the function itself.
            argcnt1 = methobj.im_func.func_code.co_argcount
            argcnt2 = method.func_code.co_argcount
            if order=='post' and ((argcnt1 + 1)!= argcnt2) or \
               order=='pre' and (argcnt1 != argcnt2):
                raise HarvestManHooksException,'Error: invalid callback method, signature does not match!'
            # Set wrapper method
            set_wrapper_method(klass, origmethod, method, order)
        else:
            pass
                          
    def get_hook_func(self, context):

        return self.run_hooks.get(context)

    def get_all_hook_funcs(self):

        return self.run_hooks.copy()

    add_all_hooks = classmethod(add_all_hooks)    
    add_hook = classmethod(add_hook)
    get_hooks = classmethod(get_hooks)
    get_all_hooks = classmethod(get_all_hooks)
    add_all_callbacks = classmethod(add_all_callbacks)
    add_callback = classmethod(add_callback)
    get_callbacks = classmethod(get_callbacks)
    get_all_callbacks = classmethod(get_all_callbacks)
    
HarvestManHooks.add_all_hooks()
HarvestManHooks.add_all_callbacks()
              
def register_plugin_function(context, func):
    """ Register function 'func' as
    a plugin at context 'context' """
    
    # The context is a string of the form module:hook
    # Example => crawler:fetcher_process_url_hook

    # Hooks are defined in modules using the global dictionary
    # __hooks__. This module will load all hooks from modules
    # supporting hookable(pluggable) function definitions, when
    # this module is imported and add the hook definitions to
    # the class HarvestManHooks.
    
    # The function is a hook function/method object which is defined
    # at the time of calling this function. This function
    # will not attempt to validate whether the hook function exists
    # and whether it accepts the right parameters (if any). Any
    # such validation is done by the Python run-time. The function
    # can be a module-level, class-level or instance-level function.
    
    module, hook = context.split(':')

    Hook = HarvestManHooks.getInstance()
    
    # Validity checks...
    if module not in HarvestManHooks.get_all_hooks().keys():
        raise HarvestManHooksException,'Error: %s has no hooks defined!' % module

    # print HarvestManHooks.get_hooks(module)
    
    if hook not in HarvestManHooks.get_hooks(module):
        raise HarvestManHooksException,'Error: Hook %s is not defined for module %s!' % (hook, module)

    # Finally add hook..
    Hook.set_hook_func(context, func)


def register_callback_method(context, method, order):
    """ Register class method 'method' as
    a callback at context 'context' according
    to given order """

    # Don't call this function directly, instead
    # use one of the function below which wraps up
    # this function.
    
    if order not in ('post','pre'):
        raise HarvestManHooksException,'Error: order argument %s is not valid!' % order
    
    # The context is a string of the form module:hook
    # Example => crawler:fetcher_process_url_hook

    # Callbackss are defined in modules using the global dictionary
    # __callbacks__. This module will load all callbacks from modules
    # having function definitions which support callbacks, when
    # this module is imported. The callback definitions are added to
    # the class HarvestManHooks.
    
    # The method 'method' is a callback instance method object which is defined
    # at the time of calling this function. The method has to be declared
    # as a class-level method with the same arguments as the original.
    # Callbacks are not supported for module level functions, i.e functions
    # not associated to classes.
    
    module, hook = context.split(':')

    Hook = HarvestManHooks.getInstance()
    
    # Validity checks...can be a module-level, class-level or instance-level function.
    if module not in HarvestManHooks.get_all_callbacks().keys():
        raise HarvestManHooksException,'Error: %s has no callbacks defined!' % module

    if hook not in HarvestManHooks.get_callbacks(module):
        raise HarvestManHooksException,'Error: Callback %s is not defined for module %s!' % (hook, module)

    # Finally add callback..
    Hook.set_callback_method(context, method, order)    
    
def register_pre_callback_method(context, method):
    """ Register callback method as a pre callback """

    return register_callback_method(context, method,'pre')

def register_post_callback_method(context, method):
    """ Register callback method as a post callback """

    return register_callback_method(context, method,'post')
    
def myfunc(self):
    pass

if __name__ == "__main__":
    register_plugin_function('datamgr:download_url_hook', myfunc)
    register_post_callback_method('crawler:fetcher_process_url_callback', myfunc)
    print HarvestManHooks.getInstance().get_all_hook_funcs()
