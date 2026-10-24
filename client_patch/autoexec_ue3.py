# Python 2.7 -- replaces autoexec_ue3 inside COMMON.SDAT (shipped as compiled .pyo; the PS3 build
# has no compiler for .py sources). tools/patch_common_sdat.py renames the original module to
# autoexec_ue3_orig.pyo; we run its bytecode unchanged and install the log forwarder after the
# original Run() has set up logging.
import marshal
import sys

exec marshal.loads(__loader__.get_data('autoexec_ue3_orig.pyo')[8:]) in globals()

_original_Run = Run


def Run():
    # Developer switch in battleClient3.OnQuitToMercQuartersNotification: on entering the merc
    # quarters, join the battle with this name. Only the fake battle of dust_server/fake_battle.json
    # is called that, so without it (enabled=false) nothing happens.
    sys.argv = list(getattr(sys, 'argv', [])) + ['-autologinbattle=LocalTest']
    _original_Run()
    try:
        import dustlogfwd
        dustlogfwd.Install()
        import dustdevhook
        dustdevhook.Install()
    except Exception:
        import traceback
        traceback.print_exc()
