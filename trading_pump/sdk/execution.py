"""Pump.fun execution client composed from the Pump.fun, PumpSwap and transport mixins.

Every name historically importable from this module is re-exported here.
"""

import asyncio
import base64
import json
from collections.abc import Sequence
from typing import Any, Optional

import aiohttp
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    close_account,
    create_idempotent_associated_token_account,
    get_associated_token_address,
    sync_native,
)
from spl.token.models import CloseAccountParams, SyncNativeParams

from trading_pump.infra.rpc_pool import (
    RpcConnectionPool,
)

from .costs import (
    TransactionCosts,
    model_transaction_costs,
    parse_transaction_costs,
)
from .curve import (
    calculate_buy_execution_slippage,
    calculate_buy_price_impact,
    calculate_buy_tokens_out,
    calculate_market_cap_sol,
    calculate_sell_execution_slippage,
    calculate_sell_price_impact,
    calculate_sell_sol_out,
    calculate_spot_price,
    curve_reserve_anomaly,
)
from .execution_types import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    BUY_DISCRIMINATOR,
    BUY_V2_DISCRIMINATOR,
    BUYBACK_FEE_RECIPIENT,
    COMPUTE_BUDGET_PROGRAM_ID,
    EVENT_AUTHORITY,
    FEE_CONFIG_KEY,
    FEE_RECIPIENT,
    GET_MULTIPLE_ACCOUNTS_LIMIT,
    GLOBAL_STATE,
    MAYHEM_FEE_RECIPIENT,
    PUMP_DEFAULT_FEE_BPS,
    PUMP_FEE_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    RENT_PROGRAM_ID,
    SELL_DISCRIMINATOR,
    SELL_V2_DISCRIMINATOR,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
    WSOL_MINT_STR,
    CurveAccountMissingError,
    CurveCompleteError,
    CurveStateUnavailableError,
    MayhemModeCurveError,
    NonStandardCurveError,
    NotPumpFunCurveError,
    TokenBalanceUnavailableError,
    TokenProgramUnavailableError,
)
from .jito import (
    JITO_BLOCK_ENGINE_ENDPOINTS,
    JITO_TIP_ACCOUNTS,
    JitoClient,
    JitoTipConfig,
)
from .pumpfun_execution import PumpFunCurveMixin
from .pumpswap import PumpSwapPoolUnavailableError
from .pumpswap_execution import PumpSwapExecutionMixin

__all__ = [
    "AccountMeta",
    "aiohttp",
    "Any",
    "ASSOCIATED_TOKEN_PROGRAM_ID",
    "asyncio",
    "base64",
    "BUY_DISCRIMINATOR",
    "BUY_V2_DISCRIMINATOR",
    "BUYBACK_FEE_RECIPIENT",
    "calculate_buy_execution_slippage",
    "calculate_buy_price_impact",
    "calculate_buy_tokens_out",
    "calculate_market_cap_sol",
    "calculate_sell_execution_slippage",
    "calculate_sell_price_impact",
    "calculate_sell_sol_out",
    "calculate_spot_price",
    "close_account",
    "CloseAccountParams",
    "COMPUTE_BUDGET_PROGRAM_ID",
    "create_idempotent_associated_token_account",
    "curve_reserve_anomaly",
    "CurveAccountMissingError",
    "CurveCompleteError",
    "CurveStateUnavailableError",
    "EVENT_AUTHORITY",
    "FEE_CONFIG_KEY",
    "FEE_RECIPIENT",
    "get_associated_token_address",
    "GET_MULTIPLE_ACCOUNTS_LIMIT",
    "GLOBAL_STATE",
    "Instruction",
    "JITO_BLOCK_ENGINE_ENDPOINTS",
    "JITO_TIP_ACCOUNTS",
    "JitoClient",
    "JitoTipConfig",
    "json",
    "Keypair",
    "MAYHEM_FEE_RECIPIENT",
    "MayhemModeCurveError",
    "MessageV0",
    "model_transaction_costs",
    "NonStandardCurveError",
    "NotPumpFunCurveError",
    "Optional",
    "parse_transaction_costs",
    "Pubkey",
    "PUMP_DEFAULT_FEE_BPS",
    "PUMP_FEE_PROGRAM_ID",
    "PUMP_PROGRAM_ID",
    "PumpFunExecutionClient",
    "PumpSwapPoolUnavailableError",
    "RENT_PROGRAM_ID",
    "RpcConnectionPool",
    "SELL_DISCRIMINATOR",
    "SELL_V2_DISCRIMINATOR",
    "Sequence",
    "sync_native",
    "SyncNativeParams",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID_STR",
    "TOKEN_PROGRAM_ID",
    "TOKEN_PROGRAM_ID_STR",
    "TokenBalanceUnavailableError",
    "TokenProgramUnavailableError",
    "TransactionCosts",
    "transfer",
    "TransferParams",
    "VersionedTransaction",
    "WSOL_MINT_STR",
]


class PumpFunExecutionClient(PumpFunCurveMixin, PumpSwapExecutionMixin):
    """Build and broadcast real Pump.fun transactions using the program instruction
    pattern.
    """
