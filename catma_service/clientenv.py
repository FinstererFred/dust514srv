# Python 2.7 -- sets up an environment in which the DUST 514 client's own Python modules (the
# original .pyo bytecode extracted from COMMON.SDAT) can be imported outside the game.
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# DUST_EXTRACTED / DUST_VAULT override the local Windows layout (used by the Docker setup in docker/)
EXTRACTED = os.environ.get('DUST_EXTRACTED') or os.path.join(ROOT, 'research', 'extracted_0319')
VAULT = os.environ.get('DUST_VAULT') or r'D:\rpcs3\dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME\VAULT'


class _Tasklet(object):
    """Minimal stand-in for stackless.tasklet: runs the function right away."""

    def __init__(self, func=None):
        self.func = func
        self.alive = False

    def __call__(self, *args, **kwargs):
        if self.func is not None:
            self.func(*args, **kwargs)
        return self

    def kill(self):
        pass


def _install_stackless_stub():
    if 'stackless' in sys.modules:
        return
    stackless = types.ModuleType('stackless')
    stackless.tasklet = _Tasklet
    stackless.getcurrent = lambda: _Tasklet()
    stackless.schedule = lambda *args: None
    stackless.channel = object
    stackless.getruncount = lambda: 1
    stackless.TaskletExit = SystemExit
    sys.modules['stackless'] = stackless


class _Placeholder(object):
    """Accepts any construction, call or attribute access; usable as a base class too."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Placeholder()


class _TolerantModule(types.ModuleType):
    """A module that hands out placeholder classes for names it does not define."""

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        placeholder = type(name, (_Placeholder,), {})
        setattr(self, name, placeholder)
        return placeholder


def _install_stacklesslib_stub():
    """stacklesslib needs real Stackless channels; plain thread primitives are enough here."""
    import threading
    import time
    package = _TolerantModule('stacklesslib')
    package.__path__ = []
    locks = _TolerantModule('stacklesslib.locks')
    locks.Lock, locks.RLock = threading.Lock, threading.RLock
    locks.Condition, locks.Event, locks.Semaphore = threading.Condition, threading.Event, threading.Semaphore
    main = _TolerantModule('stacklesslib.main')
    main.sleep = time.sleep
    main.elapsed_time = time.time
    util = _TolerantModule('stacklesslib.util')
    util.atomic = _NullContext
    for name, module in (('locks', locks), ('main', main), ('util', util)):
        setattr(package, name, module)
        sys.modules['stacklesslib.' + name] = module
    sys.modules['stacklesslib'] = package


class _NullContext(object):

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# Native modules the game provides from C++; outside the engine they become tolerant placeholders.
NATIVE_MODULES = ['_pyunreal', 'logUE3', 'libhttp']


class _NativeModuleFinder(object):
    """Import hook: CCP's native extensions are named _py*; hand out placeholders for them."""

    def find_module(self, fullname, path=None):
        if fullname.split('.')[0].startswith('_py') or fullname in NATIVE_MODULES:
            return self
        return None

    def load_module(self, fullname):
        if fullname not in sys.modules:
            module = _TolerantModule(fullname)
            module.__path__ = []
            module.__loader__ = self
            sys.modules[fullname] = module
        return sys.modules[fullname]


def setup():
    """Put the client's modules on sys.path (game code first, then the game's extra libraries)."""
    _install_stackless_stub()
    _install_stacklesslib_stub()
    import time
    if not any(isinstance(f, _NativeModuleFinder) for f in sys.meta_path):
        sys.meta_path.append(_NativeModuleFinder())
    __import__('_pyunreal').GetAppTime = time.time
    for sub in ('COMMON', 'PYTHON'):
        path = os.path.join(EXTRACTED, sub)
        if path not in sys.path:
            sys.path.insert(1, path)
    sys.FinalRelease = True
    sys.noLogging = False
    sys.hasPyCompiler = True
    _import_sake_platform()


def _import_sake_platform():
    """sake.platform knows only win32 and PS3; its win32 variant is plain Python (appPath), so use it on Linux too."""
    if sys.platform == 'win32' or 'sake.platform' in sys.modules:
        return
    real_platform = sys.platform
    sys.platform = 'win32'
    try:
        __import__('sake.platform')
    finally:
        sys.platform = real_platform
