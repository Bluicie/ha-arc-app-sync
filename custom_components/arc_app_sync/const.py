"""Constants for the Arc Launcher App Sync integration."""

DOMAIN = "arc_app_sync"
ARC_DOMAIN = "arc_launcher"

ADB_PORT = 5555
PLAY_STORE = "com.android.vending"

CONF_LEADER = "leader"
CONF_FULL_TVS = "full_tvs"
CONF_KIDS_TVS = "kids_tvs"
CONF_MUST_HAVE = "must_have"
CONF_KIDS_ALLOWLIST = "kids_allowlist"
CONF_MAX_REMOVALS = "max_removals"
CONF_SYNC_TIME = "sync_time"
CONF_DRY_RUN = "dry_run"

LEADER_AUTO = "auto"
DEFAULT_MAX_REMOVALS = 5
DEFAULT_SYNC_TIME = "19:00:00"

PROFILE_FULL = "full"
PROFILE_KIDS = "kids"

# Never removed anywhere: the launchers these TVs are run with.
ALWAYS_PROTECTED = frozenset({"com.bluicie.arc", "com.omeda.arc", "com.spocky.projengmenu"})

# Per-TV status after a run.
STATUS_NEVER = "never"
STATUS_OK = "ok"
STATUS_DRY_RUN = "dry_run"
STATUS_ATTENTION = "attention"
STATUS_ASLEEP = "asleep"
STATUS_UNREACHABLE = "unreachable"
STATUS_LEADER_UNAVAILABLE = "leader_unavailable"
STATUSES = [
    STATUS_NEVER,
    STATUS_OK,
    STATUS_DRY_RUN,
    STATUS_ATTENTION,
    STATUS_ASLEEP,
    STATUS_UNREACHABLE,
    STATUS_LEADER_UNAVAILABLE,
]
