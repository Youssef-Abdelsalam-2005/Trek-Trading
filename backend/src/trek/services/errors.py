from __future__ import annotations


class SwapError(Exception):
    pass


class JupiterApiError(SwapError):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Jupiter API returned {status_code}: {body}")


class InsufficientBalanceError(SwapError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or "Insufficient balance for swap")


class SlippageExceededError(SwapError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or "Slippage tolerance exceeded")


class SignerError(SwapError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"Signer service error: {detail}")


class SignerUnavailableError(SignerError):
    def __init__(self) -> None:
        super().__init__("Signer service is not reachable")


class TransactionExpiredError(SwapError):
    def __init__(self, signature: str, last_valid_block_height: int) -> None:
        self.signature = signature
        self.last_valid_block_height = last_valid_block_height
        super().__init__(
            f"Transaction {signature} expired (lastValidBlockHeight={last_valid_block_height})"
        )


class TransactionConfirmationError(SwapError):
    def __init__(self, signature: str, detail: str) -> None:
        self.signature = signature
        super().__init__(f"Confirmation failed for {signature}: {detail}")


class RpcError(SwapError):
    def __init__(self, method: str, code: int | None, message: str) -> None:
        self.method = method
        self.code = code
        super().__init__(f"RPC {method} error ({code}): {message}")
