# Python 2.7 -- runs inside the DUST 514 client.
# Developer commands from the dev server: once the merc quarters are loaded, the client polls
# GET /dev/commands/ (dust_server/dev_commands.json) and runs each new revision's commands once.
# The PS3 build cannot compile Python source, so commands are a fixed set of actions, not code.
import logging
import sys

log = logging.getLogger('dustdevhook')
POLL_SECONDS = 3
_state = {'polling': False, 'revision': None}


def _InitBattleServices(svc, arg):
    # What userClient.OfflineConnect does first: start the battle server services in this process.
    svc.app.GetService('userClient')._InitBattleServices()


def _OfflineBattleConnect(svc, arg):
    # Fake inventory, skills and fittings for the offline characters (userBattle.OfflineConnect).
    svc.app.GetService('userBattle').OfflineConnect()


def _MarkInBattle(svc, arg):
    # So that the next NotifyMapLoaded counts as a battle map (dustUnreal.NotifyMapLoaded).
    svc._SetLocationInBattle()


def _Notify(svc, arg):
    svc.notificationShared.SendLocalNotification(arg)


def _Call(svc, arg):
    # {"service": "dustClient", "method": "ForceRespawn", "args": []}
    method = getattr(svc.app.GetService(arg['service']), arg['method'])
    log.info('dev call result: %r', method(*arg.get('args', [])))


ACTIONS = {
    'ue3': lambda svc, arg: svc.RunUE3Command(arg),
    'init_battle_services': _InitBattleServices,
    'offline_battle_connect': _OfflineBattleConnect,
    'mark_in_battle': _MarkInBattle,
    'notify': _Notify,
    'call': _Call,
    'sleep': lambda svc, arg: svc.app.Sleep(float(arg)),
}


def _RunCommands(svc, data):
    for command in data.get('commands', []):
        action, arg = command.get('action'), command.get('arg')
        log.info('dev command: %s %r', action, arg)
        try:
            ACTIONS[action](svc, arg)
        except Exception:
            log.exception('dev command failed: %s %r', action, arg)


def _Poll(svc):
    session = svc.app.GetService('characterConnectionClient').httpSession
    while True:
        try:
            data = session.Resource('/dev/commands/').Get(accept='vnd.ccp.eve.Api-v3')
            revision = data.get('revision')
            if revision and revision != _state['revision']:
                _state['revision'] = revision
                log.info('dev commands revision %s', revision)
                _RunCommands(svc, data)
        except Exception:
            log.exception('dev command poll failed')
        svc.app.Sleep(POLL_SECONDS)


def OnMQLoaded(svc):
    if not _state['polling']:
        _state['polling'] = True
        svc.New(_Poll, svc)


def _PatchDustUnreal(module):
    cls = module.DustUnreal
    originalStartProcess = cls.StartProcess

    def StartProcess(self):
        originalStartProcess(self)
        self.notificationShared.AddLocalListener(self, 'OnMQLoadedNotification')

    def OnMQLoadedNotification(self):
        OnMQLoaded(self)

    cls.StartProcess = StartProcess
    cls.OnMQLoadedNotification = OnMQLoadedNotification
    log.info('dustdevhook: patched dust.dustUnreal.DustUnreal')


PATCHES = {'dust.dustUnreal': _PatchDustUnreal}


class _PatchFinder(object):
    """Lets the normal import load a module from PATCHES, then patches it before anyone uses it."""

    def __init__(self):
        self.loading = set()

    def find_module(self, fullname, path=None):
        if fullname in PATCHES and fullname not in self.loading:
            return self
        return None

    def load_module(self, fullname):
        self.loading.add(fullname)
        try:
            __import__(fullname)
        finally:
            self.loading.discard(fullname)
        module = sys.modules[fullname]
        PATCHES[fullname](module)
        return module


def Install():
    for name, patch in PATCHES.items():
        if name in sys.modules:
            patch(sys.modules[name])
    sys.meta_path.append(_PatchFinder())
