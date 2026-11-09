"""Real Float, LaunchLab and CPMM records from mainnet (FEAT-179).

Read on 2026-11-09, for ``float_events`` and ``float_capture``. The logs are
trimmed to the lines the decoders read (each program's invoke and its end,
instruction names, ``Program data:``); the rest of each log was compute-unit
lines and other programs' messages. The migration transaction keeps its
account keys and top-level instructions. Accounts are ``getAccountInfo`` reads.
"""

from __future__ import annotations

from typing import Any

LAUNCH_SIGNATURE = (
    "ut2rsuWetqhn7Z7soZQDC3ZFLbDzPK3B27o5WeD5Ns23iMn9PqaQou8vfBVe"
    "ctvS9ejYvLziDK3GvY256YcMqs4"
)
LAUNCH_SLOT = 466174091
LAUNCH_LOGS: list[str] = [
    "Program ComputeBudget111111111111111111111111111111 invoke [1]",
    "Program ComputeBudget111111111111111111111111111111 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
    "Program ComputeBudget111111111111111111111111111111 invoke [1]",
    "Program ComputeBudget111111111111111111111111111111 success",
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX invoke [1]",
    "Program log: Instruction: LaunchKeyed",
    "Program 11111111111111111111111111111111 invoke [2]",
    "Program 11111111111111111111111111111111 success",
    "Program 11111111111111111111111111111111 invoke [2]",
    "Program 11111111111111111111111111111111 success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [2]",
    "Program log: Instruction: InitializeV2",
    "Program 11111111111111111111111111111111 invoke [3]",
    "Program 11111111111111111111111111111111 success",
    "Program 11111111111111111111111111111111 invoke [3]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [3]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [3]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [3]",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
    (
        "Program data: l9fiCXahc64OvgSxD55W0uYStOn18a4LrJCQJRwNyfOPYn"
        "uc1jdP4VupmKdtPpqPxs0zvXe0HcucFMFfHMqlWUCFFwEhkmd/VxqOAcjfeC"
        "D51ms8c2W40eSvqBt4VMwu91zvWL0Ihn4GCwAAAEZpbmFuY2UgSW51AgAAAE"
        "ZJXQAAAGh0dHBzOi8vZmxvYXQubXlwaW5hdGEuY2xvdWQvaXBmcy9iYWZrcm"
        "VpZnd1eGxkbnAzZ2F3cHRxM3g1NXk1aWhpdXlxZmN4YnFxd2VqM3E1dG1mc2"
        "9iYjJjaDY3aQAAgMakfo0DAABITHI0mgIAesv9HFwAAAABAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAA=="
    ),
    "Program metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s invoke [3]",
    "Program 11111111111111111111111111111111 invoke [4]",
    "Program 11111111111111111111111111111111 success",
    "Program 11111111111111111111111111111111 invoke [4]",
    "Program 11111111111111111111111111111111 success",
    "Program 11111111111111111111111111111111 invoke [4]",
    "Program 11111111111111111111111111111111 success",
    "Program metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
    (
        "Program data: Oya+5iEiWRQyhWvkKBoAl6zJv273LjLt/wS08pTWL4eJhm"
        "PsxP/kXQabiFf+q4GE+2h/Y0YYwDXaxDncGus7VZig8AAAAAABDr4EsQ+eVt"
        "LmErTp9fGuC6yQkCUcDcnzj2J7nNY3T+Fi+d68uTNZhOqS247BMlkW6SOm6t"
        "EWV/M5Lgj0R2XZy2L53ry5M1mE6pLbjsEyWRbpI6bq0RZX8zkuCPRHZdnLAA"
        "IAAABGSQE="
    ),
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX success",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 invoke [1]",
    "Program L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95 success",
]

BUY_SIGNATURE = (
    "qysdTHKPQCoqhhHtF7rertZUUqMMKUV4sp6nEwZ3TMTL29HTJJCqw3mx3B9p"
    "RY8fPBi8amnwXo6yPhBKvGTe5GD"
)
BUY_SLOT = 466174091
BUY_LOGS: list[str] = [
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [2]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL success",
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [1]",
    "Program log: Instruction: BuyExactIn",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [2]",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
    (
        "Program data: vdt/007mYe4OvgSxD55W0uYStOn18a4LrJCQJRwNyfOPYn"
        "uc1jdP4QBITHI0mgIA3WJJpnMZBAC+tWj9NAAAAAAAAAAAAAAAAAAAAAAAAA"
        "CaVg3+4BYAAMzdUy4BAAAAkKRhMQEAAACaVg3+4BYAALFxwwAAAAAA3BDVAQ"
        "AAAAA3RHUAAAAAAAAAAAAAAAAAAAAB"
    ),
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [2]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
]

SELL_SIGNATURE = (
    "52LsX9piv4qQ9sEhUsEW2QaFV8iXZeGLEBNuCSvWyPng6ycvjyRvBNtEQJmL"
    "ZHUAHy8azaYK5xpVStYDxxaWEHJs"
)
SELL_SLOT = 466177684
SELL_LOGS: list[str] = [
    "Program DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH invoke [1]",
    "Program log: Instruction: Swap",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [3]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [2]",
    "Program log: Instruction: SellExactIn",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [3]",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
    (
        "Program data: vdt/007mYe4OvgSxD55W0uYStOn18a4LrJCQJRwNyfOPYn"
        "uc1jdP4QBITHI0mgIA3WJJpnMZBAC+tWj9NAAAAC+6QYkYlwIAkpMS8loAAA"
        "CBo3y+lpYCALxJyMFaAAAArhbFyoEAAABgqs4vAAAAAN7nHgAAAAAAeixKAA"
        "AAAAAeixIAAAAAAAAAAAAAAAAAAQAB"
    ),
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
    "Program DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH invoke [2]",
    "Program DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH success",
    "Program data: ZHIw",
    "Program TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH success",
    "Program DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH invoke [2]",
    "Program DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
]

CPMM_SWAP_SIGNATURE = (
    "21HbuGgwhrBZ2YmfvCiGuLqN6uQaEmi1aaNwZUjahMrji1xz7VFZVYA8xvDT"
    "tH1fi2EucphPbauV5XmmqSqMoDHD"
)
CPMM_SWAP_SLOT = 466177690
CPMM_SWAP_LOGS: list[str] = [
    "Program ComputeBudget111111111111111111111111111111 invoke [1]",
    "Program ComputeBudget111111111111111111111111111111 success",
    "Program ComputeBudget111111111111111111111111111111 invoke [1]",
    "Program ComputeBudget111111111111111111111111111111 success",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL invoke [1]",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL success",
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
    "Program 11111111111111111111111111111111 invoke [1]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C invoke [1]",
    "Program log: Instruction: SwapBaseInput",
    (
        "Program data: QMbN6CYIceKAmZxm5VTvzuusaaLyhshlfi8xCCg1Y/Qdo/"
        "fQHltmPS3P/RxcAAAAADh6MkrzAAAQJwAAAAAAAOkjZgAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAEGm4hX/quBhPtof2NGGMA12sQ53BrrO1WYoPAAAAAAATKFa+"
        "QoGgCXrMm/bvcuMu3/BLTylNYvh4mGY+zE/+RdAwAAAAAAAABhAAAAAAAAAA"
        "E="
    ),
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C success",
]

FEE_CYCLE_SIGNATURE = (
    "612UkSNWcPYo5RduLQMpjayS7USyQRim2yEJ8vVSU5xttYm2p4HzNruTWBUE"
    "kTaEBkTPQzUd5oFULjLfe7Kz2Sz"
)
FEE_CYCLE_LOGS: list[str] = [
    "Program ComputeBudget111111111111111111111111111111 invoke [1]",
    "Program ComputeBudget111111111111111111111111111111 success",
    "Program ComputeBudget111111111111111111111111111111 invoke [1]",
    "Program ComputeBudget111111111111111111111111111111 success",
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX invoke [1]",
    "Program log: Instruction: PayHolders",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    (
        "Program data: q0wWRj4621Mk2M9bPpx57PUVrb0GQIQ/lOEeklTSHaJ7KX"
        "//bYiZI8b6evO+2606PWXzaqvJdDGxu+TC0vbg5HymAgNFL11hCgCrLQIAAA"
        "AAAA=="
    ),
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX success",
]

CLAIM_SIGNATURE = (
    "3GLGL1ducqX8Mrfi9hTyfuCauKRZWjZhnuisBRt7VDY4dpBEn3H9h7tLRdJ3"
    "HLXKPogzJYqSJXinD8japZHLgN2D"
)
CLAIM_LOGS: list[str] = [
    "Program ComputeBudget111111111111111111111111111111 invoke [1]",
    "Program ComputeBudget111111111111111111111111111111 success",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL invoke [1]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program 11111111111111111111111111111111 invoke [2]",
    "Program 11111111111111111111111111111111 success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL success",
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX invoke [1]",
    "Program log: Instruction: ClaimCoinFees",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [2]",
    "Program log: Instruction: ClaimCreatorFee",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
    (
        "Program data: d5aBt2rDQYtoUiBiaVO/ZsQWlDYKCRwtHtl4HZlfFKlBvn"
        "rTFWf80zmDTe+d0IP2jD/aTO2kACtvMlis10qT4iosQWntnRAi7hsAAAAAAA"
        "D7BgAAAAAAAPMUAAAAAAAA"
    ),
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX success",
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX invoke [1]",
    "Program log: Instruction: Harvest",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [2]",
    "Program log: Instruction: ClaimPlatformFeeFromVault",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [3]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    (
        "Program data: 22GicIgZRagAOYNN753Qg/aMP9pM7aQAK28yWKzXSpPiKi"
        "xBae2dECK7bwAAAAAAAOEwAAAAAAAA4TAAAAAAAAD5DQAAAAAAAA=="
    ),
    "Program 3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX success",
]

MIGRATION_TX: dict[str, Any] = {
    "slot": 466177688,
    "blockTime": 1793982718,
    "transaction": {
        "signatures": [
            (
                "5e4Z9VHjqCtJGz8tS8ttRxz5oLzxuurgXnRSCNzx9pme4eeCWD2NNufUtKwn"
                "iXsQpftzVeffnYiTTNG4vE3g5ff2"
            ),
            (
                "ykBdqjr5ZDMbQS9a4c3eyzPdXvKrSK3XKvTJBZsiUEtaxYtRKsjW4uVAfbVs"
                "ae2zNyT5L2KpHgj8SgnujZshqLL"
            ),
        ],
        "message": {
            "header": {
                "numRequiredSignatures": 2,
                "numReadonlySignedAccounts": 0,
                "numReadonlyUnsignedAccounts": 5,
            },
            "accountKeys": [
                "RAYpQbFNq9i3mu6cKpTKKRwwHFDeK5AuZz8xvxUrCgw",
                "DCwEWHxwKwfSptzUa4vn9yDZu3qVN2wUkg7gvTbCsEoy",
                "4QDPF5TtNAKtU5p5pvcq9h9b44nRSikRzNrKzsUfLoat",
                "9f13JFmgNwusTQmY86S7EA1aG4qULw39UgGN19wenCex",
                "W2rKHFERv88zMfPffgSvqDRPfeN7xWj2AaXP2q3SshH",
                "DtiEPPzwXSF8cXTEmxDsjwhQotfzGzx6UaveL9ozwiuW",
                "9W1jk3Xp24MmwagZ7wqkFjf9Dt7d2yjQH9xZULmbSSai",
                "9UUiYYyRksU8Qt2Sq8gfoH9rZmLsSfayCt5Tzey2CFnc",
                "2gerWLVHwkiTR184zj3QbGZasm3j5dQ13d7sE5oEMdh4",
                "zYm8oYadcdGes4jPRU4h2tcg4cjNVExYiyQnJParuBN",
                "DeSdyfomEKbpU46KDEoM8MmgdVSPJjXeLEjCciuUtzi7",
                "83M1v58m3byPZKyvjddSmZE9ttSLimd4RuwSJrbxSPQ1",
                "8xmigk5tpPVZbyvzNBRyyPUjV62ee3syvpkiykGb4g7b",
                "81wf6qE4sJ5Rgn4yGvEcZYCq4N35pibUVmELVDH3wdz4",
                "85jAb8cfUNq7QkwBpPPUNVDJm6m8CG1rYxfjZk7WLuvb",
                "7QHhFeNmmqEWhEWm9frm3cR6aQ63Xn59sdBu6cBrtFKh",
                "DH2iStpY9X6SMPdQtJRKbxUW76TysmacKp3oA5kZYJjF",
                "7Ap6MbHax1uGCvcBbJoGzXTLSZeQCjMgeTDLNk7S8KZG",
                "ComputeBudget111111111111111111111111111111",
                "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
                "2TDPJJPV6nvTEqXABxrqno6Uzpipxxvh1zjLN3SMYn69",
                "E2RwEokgH5mc15AowLQJkE532cMbgCboEMWcefZei1EJ",
                "49UNMxpJRJtmxTMasVdZp81dXY9uEChfW5mjn34CBmrw",
            ],
            "instructions": [
                {
                    "programIdIndex": 18,
                    "accounts": [],
                    "data": "EX9Qeb",
                    "stackHeight": 1,
                },
                {
                    "programIdIndex": 18,
                    "accounts": [],
                    "data": "3aEBj4DhQCvT",
                    "stackHeight": 1,
                },
                {
                    "programIdIndex": 19,
                    "accounts": [
                        0,
                        2,
                        26,
                        20,
                        27,
                        3,
                        28,
                        4,
                        5,
                        6,
                        29,
                        23,
                        7,
                        30,
                        31,
                        8,
                        24,
                        9,
                        25,
                        10,
                        11,
                        12,
                        32,
                        33,
                        34,
                        35,
                        36,
                        37,
                        13,
                        1,
                        14,
                        15,
                        16,
                        17,
                        38,
                        35,
                        21,
                        22,
                    ],
                    "data": "PotQtwz6wf1",
                    "stackHeight": 1,
                },
            ],
        },
    },
    "meta": {
        "loadedAddresses": {
            "writable": [
                "DNXgeM9EiiaAbaWvwjHj9fQQLAX5ZsfHyvmYUNRAdNC8",
                "WLHv2UAZm6z4KyaaELi5pjdbJh6RESMva1Rnn8pJVVh",
                "6s1xP3hpbAfFoNtUNF8mfHsjr2Bd97JxFJRWLbL6aHuX",
            ],
            "readonly": [
                "So11111111111111111111111111111111111111112",
                "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
                "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",
                "9UQpPzgjju8DhHGcdnGDuXck4VGnHzGhRxT2NmEr6aS8",
                "LockrWmn6K5twhz3y9w1dQERbmgSaRkfnTeTKbpofwE",
                "3f7GcQFG397GAaEnv51zR6tsTVihYRydnydDD1cXekxH",
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
                "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
                "11111111111111111111111111111111",
                "SysvarRent111111111111111111111111111111111",
                "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s",
                "7NrevmQXcRTRGsgruwTCwWkn9qwA29rXcMwfenWunHP",
            ],
        },
        "innerInstructions": [],
    },
}

ACCOUNTS: dict[str, dict[str, Any]] = {
    "float_config": {
        "address": "AgaKFP4SfEeeM4r4GcSWBwpEAbfHh7wLkJGHqpWrLBQV",
        "owner": "3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX",
        "data": [
            (
                "mwyq4B76zIIY7ZRog05ABB3k1OxUp8CURGGV3oNP0CamoFzS1cevMxPQ6Byf"
                "bAyAchE/ysNkGds0xptsHdkKajt6DBsUxy8T3AX0AawNrA3oA0wdAAAAAAAA"
                "XEQAAAAAAADkVwAAAAAAAAMVksqGDGviF4o8ub5o/P3hElthT+OKDJMPliqi"
                "4b8BNmVWMHQmw4FDD18c/XIMJE4tpowpANbu2AcWh1OT846zqEJqpQ5m2ES5"
                "iYkJIO8axiss7A0bBsvPnJwzw79clGqiKUw12x/+Tu2k5BHIVZZJiCSvJOxt"
                "DFwxyFeSqXRRmVgCAADIAAAAZAAAlDV3AAAAAAAAAAAAAAAAAIDGpH6NAwCd"
                "HABPTEeHNhX4JlMjFmtCF6Im+cgGDbZDsHEf08fe6HLwtwAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAMb6evO+2606PWXzaqvJdDGxu+TC0vbg5HymAgNF"
                "L11hXkPcsx0AAADm/yX4BmMAAAD+"
            ),
            "base64",
        ],
    },
    "platform": {
        "address": "2TDPJJPV6nvTEqXABxrqno6Uzpipxxvh1zjLN3SMYn69",
        "owner": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
        "data": [
            (
                "oE6AAPhT5qAuBAAAAAAAAGg/m/d69Bl3mgfPoN/yiiHUElCU/g/a5qgLp74n"
                "YDSNaD+b93r0GXeaB8+g3/KKIdQSUJT+D9rmqAunvidgNI1AQg8AAAAAAAAA"
                "AAAAAAAAAAAAAAAAAABwFwAAAAAAAEZsb2F0AAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABodHRw"
                "czovL3d3dy5mbG9hdGxhdW5jaC54eXoAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaHR0cHM6Ly93d3cuZmxvYXRs"
                "YXVuY2gueHl6L2ljb24ucG5nAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAH3jG4BeBbownMn9DviOP4S9X2S2Us/4ayW+t5/BzSPN"
                "3AUAAAAAAABoP5v3evQZd5oHz6Df8ooh1BJQlP4P2uaoC6e+J2A0jWg/m/d6"
                "9Bl3mgfPoN/yiiHUElCU/g/a5qgLp74nYDSNAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            ),
            "base64",
        ],
    },
    "launch_pool": {
        "address": "zYm8oYadcdGes4jPRU4h2tcg4cjNVExYiyQnJParuBN",
        "owner": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
        "data": [
            (
                "9+3j9dfD3kY3BAAAAAAAAPoCBgkBAIDGpH6NAwAASExyNJoCAN1iSaZzGQQA"
                "vrVo/TQAAAAASExyNJoCAC3P/RxcAAAAesv9HFwAAAC3QQKVAQAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAVxqOAcjfeCD51ms8c2W40eSvqBt4VMwu91zvWL0Ihn4VksqGDGvi"
                "F4o8ub5o/P3hElthT+OKDJMPliqi4b8BNjKFa+QoGgCXrMm/bvcuMu3/BLTy"
                "lNYvh4mGY+zE/+RdBpuIV/6rgYT7aH9jRhjANdrEOdwa6ztVmKDwAAAAAAG7"
                "47i0mOE4XN6Qj0zGDCUQXnxtY25OpCr/jhEjfxKsPGibmh2FhOkVdCV/mTDa"
                "1BpghjLim7BTyt68y9fHvTumW6mYp20+mo/GzTO9d7Qdy5wUwV8cyqVZQIUX"
                "ASGSZ38AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            ),
            "base64",
        ],
    },
    "cpmm_pool": {
        "address": "9f13JFmgNwusTQmY86S7EA1aG4qULw39UgGN19wenCex",
        "owner": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
        "data": [
            (
                "9+3j9dfD3kZ94xuAXgW6MJzJ/Q74jj+EvV9ktlLP+Gslvrefwc0jzVupmKdt"
                "PpqPxs0zvXe0HcucFMFfHMqlWUCFFwEhkmd/fkwsEIY4sq60Er9DZ5mJloyG"
                "AWD6f/lxxSL0jvDP6e+/i3vzw+cXJ8WjPron2vAbWVGlaHdctsNOTfrc7y5C"
                "6Qdv74DnSMz7UitC9G6qHKkG9a6+kYVawwJxZlY5uUFwBpuIV/6rgYT7aH9j"
                "RhjANdrEOdwa6ztVmKDwAAAAAAEyhWvkKBoAl6zJv273LjLt/wS08pTWL4eJ"
                "hmPsxP/kXQbd9uHXZaGT2cvhRs7reawctIXtX1s3kTqM9YV+/wCpBt324ddl"
                "oZPZy+FGzut5rBy0he1fWzeROoz1hX7/AKl954QiUO1mI7qv+SPkCZYtePKd"
                "hL7lfh1zxy1vXtMt1f0ACQkGzZmdlEwJAAA2BxAEAAAAALy94DYBAAAAmLN9"
                "AQAAAAA81lf5CQAAAP8A7moAAAAAOQQAAAAAAAABAQAAAAAAAP94jAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAA=="
            ),
            "base64",
        ],
    },
    "mint": {
        "address": "4QDPF5TtNAKtU5p5pvcq9h9b44nRSikRzNrKzsUfLoat",
        "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "data": [
            (
                "AAAAAAeDqBUmIQ+UoOjoTSCHADs6QmDSnOedrP4hpOp3H6YoMGhOMHuNAwAG"
                "AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
            ),
            "base64",
        ],
    },
}
