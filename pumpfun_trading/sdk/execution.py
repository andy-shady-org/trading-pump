import asyncio
import base64
import json
from typing import Optional

import aiohttp
import base58
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageHeader, MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    create_associated_token_account,
    get_associated_token_address,
)

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
GLOBAL_STATE = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
FEE_RECIPIENT = "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
RENT_PROGRAM_ID = "SysvarRent111111111111111111111111111111111"
EVENT_AUTHORITY = "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1"
TOKEN_PROGRAM_ID_STR = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

BUY_DISCRIMINATOR = bytes([102, 6, 61, 18, 1, 218, 235, 234])
SELL_DISCRIMINATOR = bytes([51, 230, 133, 164, 1, 127, 131, 173])


class PumpFunExecutionClient:
    """Build and broadcast real Pump.fun transactions using the program instruction pattern."""

    @staticmethod
    def _decode_keypair(private_key_b58: str) -> Keypair:
        decoded = base58.b58decode(private_key_b58)
        if len(decoded) == 32:
            return Keypair.from_seed(decoded)
        if len(decoded) == 64:
            return Keypair.from_bytes(decoded)
        raise ValueError(
            "Private key must be a base58-encoded Solana 32-byte seed or 64-byte secret key; "
            f"got {len(decoded)} bytes after decoding."
        )

    def __init__(
        self,
        private_key_b58: str,
        rpc_url: str,
        *,
        priority_fee_lamports: int = 5000,
        default_slippage_bps: int = 500,
    ):
        self.private_key_b58 = private_key_b58
        self.rpc_url = rpc_url
        self.priority_fee_lamports = priority_fee_lamports
        self.default_slippage_bps = default_slippage_bps
        self.keypair = self._decode_keypair(private_key_b58)
        self.wallet = self.keypair.pubkey()

    @staticmethod
    def is_valid_pubkey(value: str) -> bool:
        try:
            Pubkey.from_string(value)
            return True
        except Exception:
            return False

    @staticmethod
    def is_valid_mint(value: str) -> bool:
        return (
            isinstance(value, str)
            and len(value) >= 32
            and PumpFunExecutionClient.is_valid_pubkey(value)
        )

    def _to_pubkey(self, value: str) -> Pubkey:
        return Pubkey.from_string(value)

    @staticmethod
    def _u64(value: int) -> bytes:
        if value < 0:
            raise ValueError("Unsigned integer cannot be negative")
        return value.to_bytes(8, byteorder="little", signed=False)

    def get_wallet_pubkey(self) -> str:
        return str(self.wallet)

    async def get_latest_blockhash(self) -> str:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getLatestBlockhash",
                "params": [{"commitment": "confirmed"}],
            }
            async with session.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"RPC getLatestBlockhash failed: HTTP {resp.status}: {body[:500]}"
                    )
                parsed = json.loads(body)
                value = parsed.get("result", {}).get("value", {})
                blockhash = value.get("blockhash")
                if not isinstance(blockhash, str):
                    raise RuntimeError(f"Invalid blockhash response: {body[:500]}")
                return blockhash

    async def get_balance_sol(self) -> float:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [str(self.wallet)],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"getBalance failed: HTTP {resp.status}: {body[:500]}"
                    )
                parsed = json.loads(body)
                result = parsed.get("result") or {}
                lamports = (
                    int(result.get("value", 0)) if isinstance(result, dict) else 0
                )
                return lamports / 1_000_000_000.0

    async def get_ata_address(self, mint: str, owner: Optional[str] = None) -> str:
        owner_pubkey = self._to_pubkey(owner or str(self.wallet))
        mint_pubkey = self._to_pubkey(mint)
        ata = get_associated_token_address(owner_pubkey, mint_pubkey, TOKEN_PROGRAM_ID)
        return str(ata)

    async def get_ata_exists(self, mint: str, owner: Optional[str] = None) -> bool:
        owner_pubkey = owner or str(self.wallet)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                owner_pubkey,
                {"programId": TOKEN_PROGRAM_ID_STR, "encoding": "jsonParsed"},
            ],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"getTokenAccountsByOwner failed: HTTP {resp.status}: {body[:500]}"
                    )
                parsed = json.loads(body)
                accounts = (parsed.get("result") or {}).get("value", [])
                for account in accounts or []:
                    info = (
                        account.get("account", {})
                        .get("data", {})
                        .get("parsed", {})
                        .get("info", {})
                    )
                    if (
                        info.get("mint") == mint
                        and str(info.get("owner")) == owner_pubkey
                    ):
                        return True
                return False

    def get_bonding_curve_pda(self, mint: str) -> tuple[str, str]:
        self.is_valid_mint(mint)
        mint_pubkey = self._to_pubkey(mint)
        program_id = self._to_pubkey(PUMP_PROGRAM_ID)
        bonding_curve_pda, _ = Pubkey.find_program_address(
            [b"bonding-curve", bytes(mint_pubkey)], program_id
        )
        fee_recipient = self._to_pubkey(FEE_RECIPIENT)
        associated_curve_pda, _ = Pubkey.find_program_address(
            [bytes(bonding_curve_pda), bytes(fee_recipient), bytes(mint_pubkey)],
            self._to_pubkey(ASSOCIATED_TOKEN_PROGRAM_ID),
        )
        return str(bonding_curve_pda), str(associated_curve_pda)

    def build_buy_instruction(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        max_sol_cost: int,
    ) -> Instruction:
        self.is_valid_mint(mint)
        self.is_valid_pubkey(bonding_curve)
        data = BUY_DISCRIMINATOR + self._u64(token_amount) + self._u64(max_sol_cost)
        mint_pubkey = self._to_pubkey(mint)
        bonding_curve_pubkey = self._to_pubkey(bonding_curve)
        user_pubkey = self.wallet

        accounts = [
            AccountMeta(
                pubkey=self._to_pubkey(GLOBAL_STATE), is_signer=False, is_writable=False
            ),
            AccountMeta(
                pubkey=self._to_pubkey(FEE_RECIPIENT), is_signer=False, is_writable=True
            ),
            AccountMeta(pubkey=mint_pubkey, is_signer=False, is_writable=False),
            AccountMeta(pubkey=bonding_curve_pubkey, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=get_associated_token_address(
                    bonding_curve_pubkey, mint_pubkey, TOKEN_PROGRAM_ID
                ),
                is_signer=False,
                is_writable=True,
            ),
            AccountMeta(
                pubkey=get_associated_token_address(
                    user_pubkey, mint_pubkey, TOKEN_PROGRAM_ID
                ),
                is_signer=False,
                is_writable=True,
            ),
            AccountMeta(pubkey=user_pubkey, is_signer=True, is_writable=True),
            AccountMeta(
                pubkey=self._to_pubkey(SYSTEM_PROGRAM_ID),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(TOKEN_PROGRAM_ID_STR),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(RENT_PROGRAM_ID),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(EVENT_AUTHORITY),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(PUMP_PROGRAM_ID),
                is_signer=False,
                is_writable=False,
            ),
        ]
        return Instruction(
            program_id=self._to_pubkey(PUMP_PROGRAM_ID), accounts=accounts, data=data
        )

    def build_sell_instruction(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        min_sol_output: int,
    ) -> Instruction:
        self.is_valid_mint(mint)
        self.is_valid_pubkey(bonding_curve)
        data = SELL_DISCRIMINATOR + self._u64(token_amount) + self._u64(min_sol_output)
        mint_pubkey = self._to_pubkey(mint)
        bonding_curve_pubkey = self._to_pubkey(bonding_curve)
        user_pubkey = self.wallet

        accounts = [
            AccountMeta(
                pubkey=self._to_pubkey(GLOBAL_STATE), is_signer=False, is_writable=False
            ),
            AccountMeta(
                pubkey=self._to_pubkey(FEE_RECIPIENT), is_signer=False, is_writable=True
            ),
            AccountMeta(pubkey=mint_pubkey, is_signer=False, is_writable=False),
            AccountMeta(pubkey=bonding_curve_pubkey, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=get_associated_token_address(
                    bonding_curve_pubkey, mint_pubkey, TOKEN_PROGRAM_ID
                ),
                is_signer=False,
                is_writable=True,
            ),
            AccountMeta(
                pubkey=get_associated_token_address(
                    user_pubkey, mint_pubkey, TOKEN_PROGRAM_ID
                ),
                is_signer=False,
                is_writable=True,
            ),
            AccountMeta(pubkey=user_pubkey, is_signer=True, is_writable=True),
            AccountMeta(
                pubkey=self._to_pubkey(SYSTEM_PROGRAM_ID),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(ASSOCIATED_TOKEN_PROGRAM_ID),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(TOKEN_PROGRAM_ID_STR),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(EVENT_AUTHORITY),
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self._to_pubkey(PUMP_PROGRAM_ID),
                is_signer=False,
                is_writable=False,
            ),
        ]
        return Instruction(
            program_id=self._to_pubkey(PUMP_PROGRAM_ID), accounts=accounts, data=data
        )

    async def build_buy_tx(
        self,
        mint: str,
        bonding_curve: str,
        sol_amount: float,
        *,
        token_amount: Optional[int] = None,
        slippage_bps: Optional[int] = None,
    ) -> VersionedTransaction:
        token_amount = token_amount if token_amount is not None else 0
        slippage_bps = (
            self.default_slippage_bps if slippage_bps is None else slippage_bps
        )
        lamports = int(sol_amount * 1_000_000_000)
        max_sol_cost = int((lamports * (10_000 + slippage_bps)) / 10_000)

        instructions = []
        if not await self.get_ata_exists(mint):
            instructions.append(
                create_associated_token_account(
                    payer=self.wallet,
                    owner=self.wallet,
                    mint=self._to_pubkey(mint),
                )
            )
        instructions.append(
            self.build_buy_instruction(mint, bonding_curve, token_amount, max_sol_cost)
        )
        return await self._build_tx_with_instructions(instructions)

    async def build_sell_tx(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        *,
        min_sol_output: int = 0,
    ) -> VersionedTransaction:
        instructions = [
            self.build_sell_instruction(
                mint, bonding_curve, token_amount, min_sol_output
            )
        ]
        return await self._build_tx_with_instructions(instructions)

    async def _build_tx_with_instructions(self, instructions) -> VersionedTransaction:
        blockhash = await self.get_latest_blockhash()
        account_keys = []
        for instruction in instructions:
            for meta in instruction.accounts:
                if meta.pubkey not in account_keys:
                    account_keys.append(meta.pubkey)
        if self.wallet not in account_keys:
            account_keys.insert(0, self.wallet)
        else:
            account_keys.remove(self.wallet)
            account_keys.insert(0, self.wallet)
        message = MessageV0(
            header=MessageHeader(
                num_required_signatures=1,
                num_readonly_signed_accounts=0,
                num_readonly_unsigned_accounts=0,
            ),
            account_keys=account_keys,
            recent_blockhash=blockhash,
            instructions=instructions,
            address_table_lookups=[],
        )
        signature = self.keypair.sign_message(bytes(message))
        return VersionedTransaction.populate(message, [signature])

    async def send_transaction(self, tx: VersionedTransaction) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(bytes(tx)).decode("utf-8"),
                {
                    "skipPreflight": True,
                    "preflightCommitment": "confirmed",
                    "encoding": "base64",
                    "maxRetries": 3,
                },
            ],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"sendTransaction failed: HTTP {resp.status}: {body[:500]}"
                    )
                parsed = json.loads(body)
                result = parsed.get("result")
                if not isinstance(result, str) or len(result) < 20:
                    raise RuntimeError(f"Invalid sendTransaction result: {body[:500]}")
                return result

    async def confirm_transaction(
        self, signature: str, max_retries: int = 20, interval: float = 1.0
    ) -> bool:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignatureStatuses",
            "params": [[signature], {"searchTransactionHistory": True}],
        }
        async with aiohttp.ClientSession() as session:
            for _ in range(max_retries):
                try:
                    async with session.post(
                        self.rpc_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status != 200:
                            continue
                        parsed = await resp.json()
                        result = (parsed.get("result") or {}).get("value")
                        if not result:
                            await asyncio.sleep(interval)
                            continue
                        status = result[0]
                        if not status:
                            await asyncio.sleep(interval)
                            continue
                        confirmation_status = status.get("confirmationStatus")
                        if confirmation_status in {
                            "processed",
                            "confirmed",
                            "finalized",
                        }:
                            if status.get("err") is None:
                                return True
                            raise RuntimeError(
                                f"On-chain transaction failed: {status.get('err')}"
                            )
                except Exception:
                    pass
                await asyncio.sleep(interval)
        return False

    async def buy(
        self,
        mint: str,
        bonding_curve: str,
        sol_amount: float,
        *,
        token_amount: Optional[int] = None,
        slippage_bps: Optional[int] = None,
    ) -> str:
        tx = await self.build_buy_tx(
            mint,
            bonding_curve,
            sol_amount,
            token_amount=token_amount,
            slippage_bps=slippage_bps,
        )
        return await self.send_transaction(tx)

    async def sell(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        *,
        min_sol_output: int = 0,
    ) -> str:
        tx = await self.build_sell_tx(
            mint, bonding_curve, token_amount, min_sol_output=min_sol_output
        )
        return await self.send_transaction(tx)

    async def get_token_balance(self, mint: str, owner: Optional[str] = None) -> int:
        """Return the token balance for the wallet ATA for a given mint, in raw token units."""
        owner_pubkey = owner or str(self.wallet)
        ata = await self.get_ata_address(mint, owner_pubkey)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountBalance",
            "params": [ata, {"commitment": "confirmed"}],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"getTokenAccountBalance failed: HTTP {resp.status}: {body[:500]}"
                    )
                parsed = json.loads(body)
                result = parsed.get("result") or {}
                amount = result.get("value", {}).get("amount")
                if amount is None:
                    return 0
                return int(amount)
