# Python 2.7 -- replaces autoexec_ue3 inside COMMON.SDAT (shipped as compiled .pyo; the PS3 build
# has no compiler for .py sources). tools/patch_common_sdat.py renames the original module to
# autoexec_ue3_orig.pyo; we run its bytecode unchanged and install the log forwarder after the
# original Run() has set up logging.
import marshal

exec marshal.loads(__loader__.get_data('autoexec_ue3_orig.pyo')[8:]) in globals()

_original_Run = Run


def Run():
    # Game arguments (RPCS3: after "--") reach sys.argv. A joining client gets
    # -autologinbattle=LocalTest there (battleClient3 joins that battle on entering the merc quarters);
    # a listen-server host must not, or it would join its own battle.
    _original_Run()
    try:
        import dustlogfwd
        dustlogfwd.Install()
        import dustdevhook
        dustdevhook.Install()
    except Exception:
        import traceback
        traceback.print_exc()
