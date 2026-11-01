# Python 2.7 -- runs inside the DUST 514 client.
# Developer commands from the dev server: once the merc quarters are loaded, the client polls
# GET /dev/commands/ (dust_server/dev_commands.json) and runs each new revision's commands once.
# The PS3 build cannot compile Python source, so commands are a fixed set of actions, not code.
import logging
import sys
import time

log = logging.getLogger('dustdevhook')
POLL_SECONDS = 3
_state = {'polling': False, 'revision': None, 'battleServer': False, 'members': set(), 'hostSpawns': 0,
          'offlineSkills': {}, 'byURI': {}, 'joined': {}, 'duration': {}, 'lost': {}, 'vehicles': {},
          'completed': False}


def _InitBattleServices(svc, arg):
    # What userClient.OfflineConnect does first: start the battle server services in this process.
    svc.app.GetService('userClient')._InitBattleServices()
    _state['battleServer'] = True


def _OfflineBattleConnect(svc, arg):
    # Fake inventory, skills and fittings for the offline characters (userBattle.OfflineConnect).
    svc.app.GetService('userBattle').OfflineConnect()


def _MarkInBattle(svc, arg):
    # So that the next NotifyMapLoaded counts as a battle map (dustUnreal.NotifyMapLoaded).
    svc._SetLocationInBattle()


def _Notify(svc, arg):
    svc.notificationShared.SendLocalNotification(arg)


def _BattleMember(svc, arg):
    # Registers a joining player with this client's battle server (listen server host), the way
    # battleServer._MemberJoinedBattle does for the backend's member notification, but without CREST
    # lookups. The joining client then connects with CleanLoad <host>:7777?credential=<credential>.
    # {"credential": "...", "characterID": 2100001612, "characterURI": "...", "name": "...", "team": 1,
    #  "host": true for the listen-server host's own player; own characters also raceID, corporationID,
    #  corporationName, gender and "skills": [[typeID, level], ...]}
    from dust.battleServer import BattleCharacterCache
    character = BattleCharacterCache()
    character.credential = arg['credential']
    character.teamID = arg.get('team', 1)
    character.characterName = arg.get('name', 'Mercenary')
    character.raceID = arg.get('raceID', 4)
    character.corporationID = arg.get('corporationID', 1000205)
    character.corporationName = arg.get('corporationName', 'Amarr Templars')
    character.characterURI = arg['characterURI']
    character.portraitURI = arg.get('portraitURI', '')
    character.gender = str(arg.get('gender', 1))
    character.characterID = arg['characterID']
    character.vipLevel = 0
    svc.app.GetService('battleServer').characterCaches[arg['characterURI']] = character
    _state['byURI'][arg['characterURI']] = arg
    if arg.get('host'):
        _state['hostCharID'] = arg['characterID']
    try:
        _BattleSkills(svc, arg)
    except Exception:
        log.exception('battle skills failed for %s', arg['characterID'])


def _BattleSkills(svc, arg):
    # A player's own skills ("skills": [[typeID, level], ...]) replace the all-level-5 skills OfflineConnect gave
    # the battle ID, the way skillBattle.OnPreCharacterConnectNotification does from CREST. Battle IDs are reused,
    # so a member without skills (CCP's offline characters, fake clients) gets OfflineConnect's state back: all
    # level 5 for the fitting check and an empty data cache, i.e. no skill bonuses in _pystims.
    from dust import skillModuleFactory
    skillBattle = svc.app.GetService('skillBattle')
    charID = arg['characterID']
    if 'skills' in arg:
        _state['offlineSkills'].setdefault(charID, skillBattle.knownSkills.get(charID))
        skillBattle.knownSkills[charID] = [
            {'skillTypeID': int(typeID), 'skillLevel': int(level), 'skillName': '',
             'href': '%s/skills/%s/' % (arg['characterURI'].rstrip('/'), typeID)}
            for typeID, level in arg['skills']]
        skillBattle._UpdateDataCache(charID)
        log.info('skills updated for character %s (%s): %s skills', charID, arg.get('name'), len(arg['skills']))
    elif charID in _state['offlineSkills']:
        skillBattle.knownSkills[charID] = _state['offlineSkills'].pop(charID)
        skillBattle.skillDataCache[charID] = skillModuleFactory.SkillDataCache()
        import _pystims
        _pystims.UpdateSkills(charID, {})
        log.info('offline skills restored for character %s', charID)


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
    'battle_member': _BattleMember,
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


def _RegisterBattleMembers(svc, session):
    # Listen-server host: the dev server lists the players that joined its fake battle
    # (dust_server/fake_battle.json, variant "listen"); register each new credential once.
    if not _state.get('battleServer'):
        return
    for member in session.Resource('/dev/battle/members/').Get(accept='vnd.ccp.eve.Api-v3').get('items', []):
        if member['credential'] not in _state['members']:
            _state['members'].add(member['credential'])
            log.info('battle member: %s %s', member['characterID'], member['characterURI'])
            _BattleMember(svc, member)


OVERVIEW_MAP_STATE_MAP = 1  # dust.ui.services.uiSvcOverviewMap
REOPEN_WATCH_SECONDS = 30


def _ReopenDeployMap(app, hostSpawns):
    # On a listen server another player's spawn also closes the host player's deploy map (once that
    # player is in, 5 to 15 seconds later), which leaves the host without a way to spawn. Open it again
    # unless the host spawned itself in the meantime.
    overviewMap = app.GetService('uiSvcOverviewMap')
    for _ in range(REOPEN_WATCH_SECONDS):
        app.Sleep(1)
        if _state['hostSpawns'] != hostSpawns:
            return
        if overviewMap.overviewMapState != OVERVIEW_MAP_STATE_MAP:
            log.info('reopening the deploy map after another player spawned')
            overviewMap.OnRequestOpenMenu(1)
            return


# --- Stage 5b: end of match. CCP's battle server posts battle.completed and member.completed to the backend; the
# listen host has no backend battle (self.battle None, self.members empty), so _CompleteBattle would fail. Instead
# we post the same payload (plus each member's credential) to the dev server, which books the rewards and answers
# with the OnEndOfMatchResults of every member; the end-of-match screen waits for them. Losses: the host runs with
# the game client's role, so inventoryBattle tracks nothing; we count the fittings destroyed with a pawn
# (fittingBattle2.DestroyFitting), consumable items as consumed and the rest as nonConsumed like CCP.

def _Session(app):
    return app.GetService('characterConnectionClient').httpSession


def _Duration(uri, stop=False):
    joined = _state['joined'].get(uri)
    if joined is not None:
        _state['duration'][uri] = _state['duration'].get(uri, 0) + int(time.time() - joined)
        _state['joined'][uri] = None if stop else time.time()
    return _state['duration'].get(uri, 0)


def _AddLost(charID, required):
    from catma import catmaDB
    cdb = catmaDB.GetDB()
    consumed, nonConsumed = _state['lost'].setdefault(int(charID), ({}, {}))
    for typeID, quantity in required.iteritems():
        target = consumed if cdb.GetTypeByID(typeID).GetValue('consumable') else nonConsumed
        target[typeID] = target.get(typeID, 0) + quantity


def _VehicleLosses(fittingBattle, charID):
    # Vehicles from the host patch have no fitting owner on their VIC (the RDV delivery sets it, which the release
    # build lacks), so UnrealScript neither destroys nor checks in their fitting. Whatever is still checked out when
    # the owner leaves or the match ends counts as lost, also a vehicle that survived (the RDV refund cannot happen).
    charID = int(charID)
    checkedOut = fittingBattle.checkedOutFittingString[charID]
    for fs in _state['vehicles'].pop(charID, []):
        entry = next((e for e in checkedOut if e[0] == fs), None)
        if entry:
            checkedOut.remove(entry)
            _AddLost(charID, entry[1])
            log.info('vehicle lost for %s: %r', charID, entry[1])


def _Lost(charID):
    lost = _state['lost'].pop(int(charID), ({}, {}))
    return [[{'type': {'href': '/types/%s/' % t}, 'quantity': q} for t, q in d.iteritems()] for d in lost]


def _ListenCompleteBattle(self, winningTeam, attackerClonesLost, defenderClonesLost):
    # dust.battleServer's own svcmgr: CCP's modules import it implicitly relative, there is no top-level "svcmgr".
    GetUnrealService = sys.modules[type(self).__module__].svcmgr.GetUnrealService
    _state['completed'] = True
    warpoints = {}
    try:
        for stat in GetUnrealService('MatchInfo').GetEndOfMatchPlayerInfoList():
            log.info('end of match stat: %r', stat)
            warpoints[stat['characteruri']] = stat['warpoints']
    except Exception:
        log.exception('end of match stats failed')
    members = []
    for uri, arg in _state['byURI'].items():
        _VehicleLosses(self.fittingBattle2, arg['characterID'])
        consumed, nonConsumed = _Lost(arg['characterID'])
        members.append({'credential': arg['credential'], 'characterID': arg['characterID'], 'characterURI': uri,
                        'team': arg.get('team', 1), 'duration': _Duration(uri, stop=True),
                        'warpoints': warpoints.get(uri) or 0, 'consumed': consumed, 'nonConsumed': nonConsumed})
    log.info('battle completed: winningTeam=%s clones lost %s/%s, %s members', winningTeam, attackerClonesLost,
             defenderClonesLost, len(members))
    results = {}
    try:
        answer = _Session(self.app).Resource('/dev/battle/completed/').Post(
            {'winningTeam': winningTeam, 'attackerClonesLost': attackerClonesLost,
             'defenderClonesLost': defenderClonesLost, 'members': members}, content='vnd.ccp.eve.Api-v3')
        results = dict((m['characterURI'], m['results']) for m in answer.get('members', []))
    except Exception:
        log.exception('posting the battle result failed')
    teamNames = {0: 'attacker', 1: 'defender'}
    for member in members:
        result = results.get(member['characterURI']) or {
            'ISKSpent': 0, 'ISKReward': 0, 'DKReward': 0, 'skillPoints': 0, 'modifierBonus': 0,
            'potentialSkillPoints': 0, 'rewardInCurrentCycle': 0, 'personalCycleCap': 0, 'corporationTax': 0,
            'corporationPercent': 0.0, 'standings': None, 'team': teamNames.get(member['team']),
            'winningTeam': teamNames.get(winningTeam)}
        log.info('end of match results for %s: %r', member['characterID'], result)
        try:
            if str(member['characterID']) == str(_state.get('hostCharID')):
                dustClient = self.app.GetService('dustClient')
                if not hasattr(dustClient, 'endOfMatchResults'):
                    dustClient.endOfMatchResults = {}  # set when a client joins a battle, which the host never does
                dustClient.OnEndOfMatchResults(result)
            else:
                self.InvokeSvcMethodOnClientAsync(member['characterID'], 'dustClient', 'OnEndOfMatchResults', result)
        except Exception:
            log.exception('sending the results to %s failed', member['characterID'])
    # CCP's battle server ends its process here (os.kill); the listen host stays up, players go back on their own.


def _ListenMemberLeft(self, characterURI, reason):
    arg = _state['byURI'].get(characterURI)
    if not arg or arg.get('host'):
        return
    _VehicleLosses(self.fittingBattle2, arg['characterID'])
    consumed, nonConsumed = _Lost(arg['characterID'])
    body = {'credential': arg['credential'], 'team': arg.get('team', 1), 'duration': _Duration(characterURI, stop=True),
            'consumed': consumed, 'nonConsumed': nonConsumed, 'reason': reason}
    log.info('battle member left: %s %r', arg['characterID'], body)
    try:
        _Session(self.app).Resource('/dev/battle/members/%s/completed/' % arg['characterID']).Post(
            body, content='vnd.ccp.eve.Api-v3')
    except Exception:
        log.exception('posting the member result failed')
    del _state['byURI'][characterURI]  # booked; a rejoin registers the player again


def _PatchBattleServer(module):
    cls = module.BattleServer
    originalSpawn = cls.SpawnCharacterWithFitting
    originalComplete = cls._CompleteBattle
    originalLeft = cls._MemberLeftBattle
    originalJoined = cls.OnBattleMemberJoinedFromUnreal

    def _CompleteBattle(self, winningTeam, attackerClonesLost, defenderClonesLost):
        if self.battle is not None or not _state['battleServer']:
            return originalComplete(self, winningTeam, attackerClonesLost, defenderClonesLost)
        if _state['completed']:
            log.info('battle already completed, ignored')
            return
        try:
            _ListenCompleteBattle(self, winningTeam, attackerClonesLost, defenderClonesLost)
        except Exception:
            # Uncaught here, the host's game disconnects from the network (UNCAUGHT_TOP_LEVEL_EXCEPTION).
            log.exception('completing the battle failed')

    def _MemberLeftBattle(self, characterURI, reason=None):
        if self.battle is None and _state['battleServer'] and not _state['completed']:
            try:
                _ListenMemberLeft(self, characterURI, reason)
            except Exception:
                log.exception('member left failed for %s', characterURI)
        return originalLeft(self, characterURI, reason)

    def OnBattleMemberJoinedFromUnreal(self, characterURI):
        _state['joined'][characterURI] = time.time()
        return originalJoined(self, characterURI)

    cls._CompleteBattle = _CompleteBattle
    cls._MemberLeftBattle = _MemberLeftBattle
    cls.OnBattleMemberJoinedFromUnreal = OnBattleMemberJoinedFromUnreal

    def SpawnCharacterWithFitting(self, _charid, fittingInfoStr):
        if str(_charid) == str(_state.get('hostCharID')):
            _state['hostSpawns'] += 1
        elif self.app.GetService('uiSvcOverviewMap').overviewMapState == OVERVIEW_MAP_STATE_MAP:
            self.New(_ReopenDeployMap, self.app, _state['hostSpawns'])
        return originalSpawn(self, _charid, fittingInfoStr)

    # OnInvokeSvcMethodFromClient checks the attributes the service decorators set (e.g. "access").
    SpawnCharacterWithFitting.__dict__.update(originalSpawn.im_func.__dict__)
    cls.SpawnCharacterWithFitting = SpawnCharacterWithFitting

    # Vehicles: the pending fitting is cleared when the RDV delivers, which the release build never does (the host
    # patch spawns the vehicle from the queue instead). A rejected request is refunded by UnrealScript, so whatever
    # is still pending was accepted: drop it without a refund, otherwise every later request is requestNotFinish.
    originalDeploy = cls.DeployVehicleWithFitting

    def DeployVehicleWithFitting(self, _charid, fittingInfoStr):
        result = originalDeploy(self, _charid, fittingInfoStr)
        if self.battle is None and self.fittingBattle2.GetPendingDeployVehicleFitting(_charid) is not None:
            self.fittingBattle2.ClearPendingVehicleFittingForChar(_charid, False)
            log.info('vehicle request of %s accepted, pending fitting cleared', _charid)
        return result

    DeployVehicleWithFitting.__dict__.update(originalDeploy.im_func.__dict__)
    cls.DeployVehicleWithFitting = DeployVehicleWithFitting
    log.info('dustdevhook: patched dust.battleServer.BattleServer')


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
            _RegisterBattleMembers(svc, session)
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


def _PatchFittingBattle(module):
    # Losses for stage 5b: what a destroyed fitting needed (checked out at spawn, not checked in again).
    cls = module.FittingBattle2
    originalDestroy = cls.DestroyFitting

    def DestroyFitting(self, charID, fittingString):
        required = next((items for fs, items in self.checkedOutFittingString[int(charID)] if fs == fittingString), None)
        destroyed = originalDestroy(self, charID, fittingString)
        if destroyed and required:
            _AddLost(charID, required)
            log.info('fitting destroyed for %s: %r', charID, required)
        return destroyed

    originalVehicle = cls.CheckOutFittingForPendingDeployVehicle

    def CheckOutFittingForPendingDeployVehicle(self, charID):
        fittingString = originalVehicle(self, charID)
        if isinstance(fittingString, basestring) and fittingString:
            _state['vehicles'].setdefault(int(charID), []).append(fittingString)
        return fittingString

    registry = module.UnrealCallableClass.func_globals['_methodRegistry'].get(cls, {})
    for name, func, original in (('DestroyFitting', DestroyFitting, originalDestroy),
                                 ('CheckOutFittingForPendingDeployVehicle', CheckOutFittingForPendingDeployVehicle,
                                  originalVehicle)):
        func.__dict__.update(original.im_func.__dict__)
        setattr(cls, name, func)
        # UE3 calls through svcmgr's registry, which UnrealCallableClass filled with the original function.
        registry[name] = func
    log.info('dustdevhook: patched dust.fittingBattle2.FittingBattle2')


PATCHES = {'dust.dustUnreal': _PatchDustUnreal, 'dust.battleServer': _PatchBattleServer,
           'dust.fittingBattle2': _PatchFittingBattle}


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
        _ApplyPatch(fullname, module)
        return module


def _ApplyPatch(name, module):
    # A broken patch must not break the import: without the module the battle services do not start at all.
    try:
        PATCHES[name](module)
    except Exception:
        log.exception('dustdevhook: patching %s failed', name)


def Install():
    for name in PATCHES:
        if name in sys.modules:
            _ApplyPatch(name, sys.modules[name])
    sys.meta_path.append(_PatchFinder())
