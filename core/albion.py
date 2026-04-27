"""
Albion Online event definitions.
Event codes are discovered at runtime via DEBUG mode — see config.json.
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')

# Default config (event codes à découvrir via le mode DEBUG)
DEFAULT_CONFIG = {
    "fame_event_codes": [],
    "silver_event_codes": [62],
    "fame_param_keys": [2],
    "silver_param_keys": [3],
    "network_ip": "",
    "debug_mode": True,
    "notes": (
        "Lancez le jeu en mode DEBUG, jouez quelques minutes "
        "puis identifiez les codes dans discovery_log.jsonl"
    )
}

# Known Albion operation codes (server → client) for reference
OP_JOIN = 2
OP_LEAVE = 4
OP_MOVE = 7
OP_ATTACK = 1

# Known param keys observed in community reverse-engineering
PARAM_FAME = 1
PARAM_PREMIUM_FAME = 2
PARAM_SILVER = 3


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                # Merge with defaults for any missing keys
                for k, v in DEFAULT_CONFIG.items():
                    cfg.setdefault(k, v)
                return cfg
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def is_fame_event(event_code: int, cfg: dict) -> bool:
    return event_code in cfg.get('fame_event_codes', [])


def is_silver_event(event_code: int, cfg: dict) -> bool:
    return event_code in cfg.get('silver_event_codes', [])


def extract_fame(params: dict, cfg: dict) -> int:
    """
    Extract fame from UpdateFame event (params[252]=82).
    params[2] = FameWithZoneMultiplier * 10000
    params[5] = IsPremiumBonus (bool, +50% if True)
    params[10] = SatchelFame * 10000
    params[17] = BonusFactor (float, default 1.0)
    """
    for key in cfg.get('fame_param_keys', [PARAM_FAME]):
        if key in params:
            val = params[key]
            if isinstance(val, (int, float)):
                raw = float(val)
                is_premium = bool(params.get(5, False))
                satchel = float(params.get(10, 0)) if isinstance(params.get(10, 0), (int, float)) else 0.0
                bonus = float(params.get(17, 1.0)) if isinstance(params.get(17, 1.0), (int, float)) else 1.0
                base = raw / 10000.0
                premium_mult = 1.5 if is_premium else 1.0
                total = (base * premium_mult + satchel / 10000.0) * bonus
                return max(0, int(total))
    return 0


def extract_silver(params: dict, cfg: dict) -> int:
    """
    Extract silver from TakeSilver event (params[252]=62).
    params[3] = YieldPreTax * 10000
    params[5] = GuildTax * 10000
    params[6] = ClusterTax * 10000
    """
    for key in cfg.get('silver_param_keys', [PARAM_SILVER]):
        if key in params:
            val = params[key]
            if isinstance(val, (int, float)):
                guild_tax  = params.get(5, 0)
                cluster_tax = params.get(6, 0)
                guild_tax  = float(guild_tax)  if isinstance(guild_tax,  (int, float)) else 0.0
                cluster_tax = float(cluster_tax) if isinstance(cluster_tax, (int, float)) else 0.0
                net = (float(val) - guild_tax - cluster_tax) / 10000.0
                return max(0, int(net))
    return 0
