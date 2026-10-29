"""Transaction assembly, fee/tip instructions, sending, Jito bundles and
confirmation."""

import asyncio
import base64
import json
from typing import Any

import aiohttp
from solders.instruction import AccountMeta, Instruction
from solders.message import MessageV0
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from .costs import (
    TransactionCosts,
    model_transaction_costs,
    parse_transaction_costs,
)
from .execution_base import ExecutionClientBase
from .execution_types import (
    COMPUTE_BUDGET_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
)
from .jito import (
    JITO_TIP_ACCOUNTS,
)


class TransactionTransportMixin(ExecutionClientBase):
    """Build, send and confirm transactions (RPC or Jito bundle) and read their
    costs."""

    async def get_latest_blockhash(self) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "confirmed"}],
        }
        parsed = await self._request_rpc_json(payload)
        value = parsed.get("result", {}).get("value", {})
        blockhash = value.get("blockhash")
        if not isinstance(blockhash, str):
            raise RuntimeError(f"Invalid blockhash response: {parsed}")
        return blockhash

    def tip_account_set(self) -> set[str]:
        """Every Jito tip account a tip may have been sent to."""
        accounts = set(JITO_TIP_ACCOUNTS)
        if self.jito_client is not None:
            accounts.update(str(a) for a in self.jito_client.tip_accounts or [])
        return accounts

    def modelled_priority_fee_lamports(self) -> int:
        """Priority fee the transaction builder attaches (compute price x limit)."""
        if self.compute_unit_limit <= 0:
            return 0
        unit_price = self.compute_unit_price_micro_lamports
        if unit_price is None:
            if self.priority_fee_lamports <= 0:
                return 0
            unit_price = int(
                (self.priority_fee_lamports * 1_000_000) / self.compute_unit_limit
            )
        return max(0, int(unit_price * self.compute_unit_limit / 1_000_000))

    def side_tip_override(self, *, is_buy: bool) -> int | None:
        """Fixed tip of one side (entry or exit), or ``None`` for the shared tip."""
        name = "jito_entry_tip_lamports" if is_buy else "jito_exit_tip_lamports"
        value = getattr(self, name, None)
        return None if value is None else max(0, int(value))

    async def resolve_trade_tip(
        self,
        *,
        is_buy: bool,
        trade_amount_sol: float = 0.0,
        conviction_score: float = 1.0,
        use_jito: bool | None = None,
    ) -> tuple[bool, int | None]:
        """``(send_via_jito, tip_lamports)`` for one trade.

        Without a side override the dynamic tip applies as before. A side tip of
        0 sends that side over plain RPC with no tip instruction; a positive one
        is paid as a fixed tip.
        """
        should_jito = self.use_jito if use_jito is None else use_jito
        if not should_jito:
            return False, None
        override = self.side_tip_override(is_buy=is_buy)
        if override is None:
            return True, await self.calculate_dynamic_jito_tip(
                trade_amount_sol=trade_amount_sol, conviction_score=conviction_score
            )
        if override == 0:
            return False, 0
        return True, override

    def model_trade_costs(
        self,
        *,
        rent_lamports: int = 0,
        signature: str | None = None,
        is_buy: bool | None = None,
    ) -> TransactionCosts:
        """Modelled costs of one trade for paper/dry-run accounting (FEAT-49).

        Uses the static ``jito_tip_lamports``, or the side's fixed tip when one
        is set and ``is_buy`` says which side; live trades may pay a higher
        dynamic tip, which is read from the transaction instead.
        """
        tip = 0
        if self.use_jito:
            override = None if is_buy is None else self.side_tip_override(is_buy=is_buy)
            tip = self.jito_tip_lamports if override is None else override
        return model_transaction_costs(
            priority_fee_lamports=self.modelled_priority_fee_lamports(),
            tip_lamports=tip,
            rent_lamports=rent_lamports,
            signature=signature,
        )

    async def get_transaction_costs(
        self,
        signature: str,
        mint: str,
        *,
        is_buy: bool,
        attempts: int = 4,
        delay_seconds: float = 0.5,
    ) -> TransactionCosts:
        """Fee, tip, rent and exact swap amount of a confirmed trade (FEAT-49).

        ``getTransaction`` can return ``null`` for a moment after confirmation, so
        it is polled a few times. Raises ``RuntimeError`` if it never appears.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "json",
                    "commitment": "confirmed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                parsed = await self.rpc_pool.request(
                    payload, max_retries=1, timeout_seconds=5.0
                )
                result = parsed.get("result") if isinstance(parsed, dict) else None
                if isinstance(result, dict):
                    return parse_transaction_costs(
                        result,
                        wallet=str(self.wallet),
                        is_buy=is_buy,
                        token_accounts=self.wallet_token_accounts(mint),
                        tip_accounts=self.tip_account_set(),
                        signature=signature,
                    )
                last_error = RuntimeError("transaction not found yet")
            except ValueError:
                raise
            except Exception as exc:
                last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(delay_seconds)
        raise RuntimeError(
            f"Transaction costs unavailable for {signature}: {last_error}"
        )

    def build_set_compute_unit_limit_instruction(
        self, units: int = 200_000
    ) -> Instruction:
        """Create ComputeBudget instruction to set max compute units."""
        data = bytes([2]) + units.to_bytes(4, byteorder="little", signed=False)
        return Instruction(
            program_id=self._to_pubkey(COMPUTE_BUDGET_PROGRAM_ID),
            accounts=[],
            data=data,
        )

    def build_set_compute_unit_price_instruction(
        self, micro_lamports: int
    ) -> Instruction:
        """Create ComputeBudget instruction to set priority fee per compute unit."""
        data = bytes([3]) + self._u64(micro_lamports)
        return Instruction(
            program_id=self._to_pubkey(COMPUTE_BUDGET_PROGRAM_ID),
            accounts=[],
            data=data,
        )

    def build_jito_tip_instruction(
        self, tip_lamports: int, tip_account: str | None = None
    ) -> Instruction:
        """Create transfer instruction sending Jito tip to validator tip address."""
        if tip_lamports <= 0:
            raise ValueError("Jito tip lamports must be positive")
        if tip_account is not None:
            target_account = tip_account
        elif self.jito_client is not None:
            target_account = self.jito_client.get_tip_account()
        else:
            target_account = JITO_TIP_ACCOUNTS[0]
        data = bytes([2, 0, 0, 0]) + self._u64(tip_lamports)
        accounts = [
            AccountMeta(pubkey=self.wallet, is_signer=True, is_writable=True),
            AccountMeta(
                pubkey=self._to_pubkey(target_account),
                is_signer=False,
                is_writable=True,
            ),
        ]
        return Instruction(
            program_id=self._to_pubkey(SYSTEM_PROGRAM_ID),
            accounts=accounts,
            data=data,
        )

    async def calculate_dynamic_jito_tip(
        self,
        trade_amount_sol: float = 0.0,
        conviction_score: float = 1.0,
    ) -> int:
        """Calculate dynamic Jito tip in Lamports based on trade amount and
        conviction."""
        if self.jito_client is not None:
            try:
                floor = await self.jito_client.fetch_tip_floor()
                return self.jito_client.calculate_tip_lamports(
                    trade_amount_sol=trade_amount_sol,
                    conviction_score=conviction_score,
                    tip_floor=floor,
                )
            except Exception:
                pass
        if self.jito_tip_lamports > 0:
            return self.jito_tip_lamports
        return self.jito_tip_config.default_tip_lamports

    def _compute_budget_instructions(self) -> list[Any]:
        """``SetComputeUnitLimit`` and ``SetComputeUnitPrice``, when set. The
        price comes from ``compute_unit_price_micro_lamports`` or, without
        it, from the priority fee spread over the unit limit."""
        budget = []
        if self.compute_unit_limit > 0:
            budget.append(
                self.build_set_compute_unit_limit_instruction(self.compute_unit_limit)
            )
        unit_price = self.compute_unit_price_micro_lamports
        if (
            unit_price is None
            and self.priority_fee_lamports > 0
            and self.compute_unit_limit > 0
        ):
            unit_price = int(
                (self.priority_fee_lamports * 1_000_000) / self.compute_unit_limit
            )
        if unit_price and unit_price > 0:
            budget.append(self.build_set_compute_unit_price_instruction(unit_price))
        return budget

    async def _build_tx_with_instructions(
        self,
        instructions,
        *,
        tip_lamports: int | None = None,
    ) -> VersionedTransaction:
        tx_instructions = self._compute_budget_instructions()
        tx_instructions.extend(instructions)
        effective_tip = (
            tip_lamports if tip_lamports is not None else self.jito_tip_lamports
        )
        if effective_tip > 0:
            # The tip is the last instruction (AGENTS: Jito tip placement).
            tx_instructions.append(self.build_jito_tip_instruction(effective_tip))

        blockhash = await self.get_latest_blockhash()
        # MessageV0.try_compile orders the account keys itself (the payer first).
        from solders.hash import Hash

        blockhash_obj = (
            Hash.from_string(blockhash) if isinstance(blockhash, str) else blockhash
        )
        message = MessageV0.try_compile(
            self.wallet,
            tx_instructions,
            [],
            blockhash_obj,
        )
        signature = self.keypair.sign_message(bytes(message))
        return VersionedTransaction.populate(message, [signature])

    async def build_sol_transfer_tx(
        self, destination: str, lamports: int
    ) -> VersionedTransaction:
        """System transfer from the wallet (profit sweep, FEAT-42); no Jito tip."""
        if int(lamports) <= 0:
            raise ValueError("Transfer lamports must be positive")
        target = self._to_pubkey(destination)
        if target == self.wallet:
            raise ValueError("Refusing to transfer SOL to the wallet itself")
        instruction = transfer(
            TransferParams(
                from_pubkey=self.wallet, to_pubkey=target, lamports=int(lamports)
            )
        )
        return await self._build_tx_with_instructions([instruction], tip_lamports=0)

    async def transfer_sol(self, destination: str, lamports: int) -> str:
        """Sends ``lamports`` to ``destination`` over RPC; returns the signature."""
        tx = await self.build_sol_transfer_tx(destination, lamports)
        return await self.send_transaction(tx)

    async def send_jito_bundle(
        self,
        transactions: list[VersionedTransaction],
        *,
        endpoint_url: str | None = None,
    ) -> str:
        """Submit a bundle of versioned transactions to Jito Block Engine."""
        url = (
            endpoint_url
            or self.jito_block_engine_url
            or "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
        )
        encoded_txs = [
            base64.b64encode(bytes(tx)).decode("utf-8") for tx in transactions
        ]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [encoded_txs, {"encoding": "base64"}],
        }
        timeout = aiohttp.ClientTimeout(total=15.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"Jito bundle submission failed (HTTP {resp.status}): "
                        f"{body[:500]}"
                    )
                parsed = json.loads(body)
                result = parsed.get("result")
                if not result:
                    raise RuntimeError(f"Invalid Jito bundle response: {parsed}")
                return str(result)

    async def send_jito_bundle_with_fallback(
        self,
        transactions: list[VersionedTransaction],
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        """Submit transactions via Jito bundle with confirmation polling and direct RPC
        fallback.
        """
        if not transactions:
            raise ValueError("Cannot submit empty transaction list as bundle")

        tx = transactions[0]
        tx_sig = str(tx.signatures[0]) if tx.signatures else ""
        timeout = timeout_seconds or self.jito_confirmation_timeout

        try:
            if self.jito_client is not None:
                return await self._land_with_jito_client(transactions, tx_sig, timeout)
            return await self._land_with_bundle_endpoint(transactions, tx_sig, timeout)
        except Exception:
            if not self.jito_fallback_to_rpc:
                raise
            self.failed_execution_attempts += 1
            self.execution_health_score = max(0.0, self.execution_health_score - 5.0)
            # Fast fallback to high-priority direct RPC submission
            return await self.send_transaction(tx)

    async def _land_with_jito_client(
        self, transactions: list[VersionedTransaction], tx_sig: str, timeout: float
    ) -> str:
        assert self.jito_client is not None
        bundle_id = await self.jito_client.send_bundle(transactions)
        status = await self.jito_client.wait_for_bundle_confirmation(
            bundle_id, timeout_seconds=timeout
        )
        if status.is_landed:
            self.execution_health_score = min(100.0, self.execution_health_score + 5.0)
            return tx_sig
        if status.is_failed:
            raise RuntimeError(f"Jito bundle {bundle_id} failed: {status.err}")
        # Unknown/pending is not a fill: fall through to the RPC fallback,
        # which re-sends the same signed tx (deduplicated by signature).
        raise TimeoutError(f"Jito bundle {bundle_id} not landed within timeout")

    async def _land_with_bundle_endpoint(
        self, transactions: list[VersionedTransaction], tx_sig: str, timeout: float
    ) -> str:
        bundle_id = await self.send_jito_bundle(transactions)
        confirmed = await self.confirm_transaction(
            tx_sig, max_retries=max(1, int(timeout))
        )
        if confirmed:
            return tx_sig
        raise TimeoutError(f"Bundle {bundle_id} not confirmed within timeout")

    async def send_transaction(self, tx: VersionedTransaction) -> str:
        async with self._execution_lock:
            encoded_tx = base64.b64encode(bytes(tx)).decode("utf-8")
            result: Any = None
            if self.rpc_pool is not None and self.rpc_pool.endpoint_count > 1:
                result = await self.rpc_pool.broadcast_transaction(
                    encoded_tx,
                    skip_preflight=True,
                    preflight_commitment="confirmed",
                )
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        encoded_tx,
                        {
                            "skipPreflight": True,
                            "preflightCommitment": "confirmed",
                            "encoding": "base64",
                            "maxRetries": 3,
                        },
                    ],
                }
                parsed = await self._request_rpc_json(payload)
                result = parsed.get("result")
            if not isinstance(result, str) or len(result) < 20:
                raise RuntimeError(f"Invalid sendTransaction result: {result}")
            self.execution_health_score = min(100.0, self.execution_health_score + 5.0)
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
        for _ in range(max_retries):
            outcome = await self._signature_outcome(payload)
            if outcome is not None:
                return outcome
            await asyncio.sleep(interval)
        return False

    async def _signature_outcome(self, payload: dict[str, Any]) -> bool | None:
        """One status poll: True / False once settled, None to poll again.

        Any error except an on-chain failure counts as "not yet"."""
        try:
            parsed = await self._request_rpc_json(payload, timeout_seconds=5.0)
            return self._settled_outcome(parsed)
        except RuntimeError as exc:
            if "On-chain transaction failed" in str(exc):
                raise
        except Exception:
            pass
        return None

    @staticmethod
    def _settled_outcome(parsed: Any) -> bool | None:
        result = (parsed.get("result") or {}).get("value")
        if not result:
            return None
        status = result[0]
        if not status:
            return None
        if status.get("confirmationStatus") not in {
            "processed",
            "confirmed",
            "finalized",
        }:
            return None
        return status.get("err") is None
