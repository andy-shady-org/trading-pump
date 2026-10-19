"""Pump.fun program constants and execution errors shared by the SDK client."""

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
# Solana caps getMultipleAccounts at 100 accounts per call.
GET_MULTIPLE_ACCOUNTS_LIMIT = 100
GLOBAL_STATE = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
FEE_RECIPIENT = "FWsW1xNtWscwNmKv6wVsU1iTzRN6wmmk3MjxRP5tT7hz"
# Global.reserved_fee_recipient: mandatory fee recipient for mayhem-mode curves
MAYHEM_FEE_RECIPIENT = "GesfTA3X2arioaHp8bbKdjG9vJtskViWACZoYvxp4twS"
BUYBACK_FEE_RECIPIENT = "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD"
PUMP_FEE_PROGRAM_ID = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
WSOL_MINT_STR = "So11111111111111111111111111111111111111112"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
RENT_PROGRAM_ID = "SysvarRent111111111111111111111111111111111"
EVENT_AUTHORITY = "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1"
TOKEN_PROGRAM_ID_STR = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID_STR = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"

BUY_DISCRIMINATOR = bytes([102, 6, 61, 18, 1, 218, 235, 234])
SELL_DISCRIMINATOR = bytes([51, 230, 133, 164, 1, 127, 131, 173])
BUY_V2_DISCRIMINATOR = bytes([184, 23, 238, 97, 103, 197, 211, 61])
SELL_V2_DISCRIMINATOR = bytes([93, 246, 130, 60, 231, 233, 64, 178])

FEE_CONFIG_KEY = bytes(
    [
        1,
        86,
        224,
        246,
        147,
        102,
        90,
        207,
        68,
        219,
        21,
        104,
        191,
        23,
        91,
        170,
        81,
        137,
        203,
        151,
        245,
        210,
        255,
        59,
        101,
        93,
        43,
        182,
        253,
        109,
        24,
        176,
    ]
)


# Pump.fun bonding-curve fees (protocol 0.95% + creator 0.30%) applied to quotes.
PUMP_DEFAULT_FEE_BPS = 125


class TokenBalanceUnavailableError(RuntimeError):
    """The token balance could not be read; distinct from a real zero (BUG-35)."""


class TokenProgramUnavailableError(RuntimeError):
    """The mint's token program (SPL Token vs Token-2022) could not be resolved."""


class CurveStateUnavailableError(RuntimeError):
    """The bonding curve (and its creator) could not be fetched for a trade."""


class NonStandardCurveError(CurveStateUnavailableError):
    """The curve's reserves don't match the standard Pump.fun layout (BUG-104)."""


class MayhemModeCurveError(NonStandardCurveError):
    """The curve is in mayhem mode, which the bot does not trade."""


class NotPumpFunCurveError(CurveStateUnavailableError):
    """The mint has no bonding curve owned by the Pump.fun program (BUG-108)."""
