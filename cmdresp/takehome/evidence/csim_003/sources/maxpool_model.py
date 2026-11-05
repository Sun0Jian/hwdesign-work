"""Bit-exact scalar model for the signed max-pool command/response stream.

This module deliberately has no NumPy dependency and no timing model. A beat is
one 32-bit data word plus TLAST. Upper payload bits are ignored on input and zero
on output. Headers have four beats: tx_id, opcode, H | (W << 16), K.
"""

from dataclasses import dataclass
from numbers import Integral
from typing import Iterable, Sequence


END = 0
COMPUTE = 1
OK = 0
HEADER_FRAMING = 1
UNKNOWN_COMMAND = 2
INVALID_PARAMETERS = 3
EARLY_PAYLOAD_TLAST = 4
MISSING_PAYLOAD_TLAST = 5


def unsigned(value: int, bits: int, field: str) -> int:
    """Reject unrepresentable values before packing; never truncate parameters."""
    if not isinstance(value, Integral) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    value = int(value)
    if not 0 <= value < 1 << bits:
        raise ValueError(f"{field} is outside unsigned {bits}-bit range: {value}")
    return value


@dataclass(frozen=True)
class Beat:
    data: int
    last: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", unsigned(self.data, 32, "beat data"))
        if self.last not in (False, True, 0, 1):
            raise ValueError("TLAST must be zero or one")
        object.__setattr__(self, "last", bool(self.last))


@dataclass(frozen=True)
class ActivationResult:
    output: tuple[Beat, ...]
    consumed: int
    remaining: tuple[Beat, ...]
    halted: int
    error: int
    error_tx_id: int


class StreamStall(RuntimeError):
    """Finite test input ended before a blocking hardware read could finish."""


def command_header(tx_id: int, opcode: int, h: int, w: int, k: int) -> list[Beat]:
    tx_id = unsigned(tx_id, 32, "tx_id")
    opcode = unsigned(opcode, 32, "opcode")
    h = unsigned(h, 16, "H")
    w = unsigned(w, 16, "W")
    k = unsigned(k, 32, "K")
    return [Beat(tx_id), Beat(opcode), Beat(h | (w << 16)), Beat(k, True)]


def input_payload(samples: Iterable[int], padding: int = 0) -> list[Beat]:
    """Pack one signed sample per beat, with explicitly chosen upper 16 bits."""
    padding = unsigned(padding, 16, "padding")
    words = []
    for sample in samples:
        if not isinstance(sample, Integral) or isinstance(sample, bool):
            raise ValueError("sample must be an integer")
        sample = int(sample)
        if not -32768 <= sample <= 32767:
            raise ValueError(f"sample is outside signed 16-bit range: {sample}")
        words.append((padding << 16) | (sample & 0xFFFF))
    return [Beat(word, index == len(words) - 1) for index, word in enumerate(words)]


def parameters_valid(h: int, w: int, k: int) -> bool:
    return (2 <= h <= 64 and 2 <= w <= 64 and k in (2, 4)
            and k <= h and k <= w and h % k == 0 and w % k == 0)


def signed_sample(word: int) -> int:
    bits = word & 0xFFFF
    return bits - 0x10000 if bits & 0x8000 else bits


def pool_scalar(samples: Sequence[int], h: int, w: int, k: int) -> list[int]:
    """Independent scalar loops; comparisons are Python signed integers."""
    if not parameters_valid(h, w, k):
        raise ValueError("invalid pooling parameters")
    if len(samples) != h * w:
        raise ValueError("sample count does not match H*W")
    for sample in samples:
        if not isinstance(sample, Integral) or isinstance(sample, bool):
            raise ValueError("sample must be an integer")
        if not -32768 <= sample <= 32767:
            raise ValueError("sample is outside signed 16-bit range")
    output = []
    for out_row in range(h // k):
        for out_column in range(w // k):
            maximum = -32768
            for inner_row in range(k):
                for inner_column in range(k):
                    sample = int(samples[(out_row * k + inner_row) * w
                                         + out_column * k + inner_column])
                    if sample > maximum:
                        maximum = sample
            output.append(maximum)
    return output


def activate(input_beats: Sequence[Beat]) -> ActivationResult:
    """Run one activation, stopping on END/error without draining queued input."""
    beats = tuple(input_beats)
    consumed = 0
    output: list[Beat] = []

    def read() -> Beat:
        nonlocal consumed
        if consumed == len(beats):
            raise StreamStall(f"input stalled after {consumed} beats")
        beat = beats[consumed]
        consumed += 1
        return beat

    def finish(error: int = OK, tx_id: int = 0) -> ActivationResult:
        return ActivationResult(tuple(output), consumed, beats[consumed:],
                                int(error != OK), error, tx_id)

    while True:
        header: list[int] = []
        for index in range(4):
            beat = read()
            header.append(beat.data)
            if beat.last != (index == 3):
                return finish(HEADER_FRAMING, header[0])
        tx_id, opcode, dimensions, k = header
        h, w = dimensions & 0xFFFF, dimensions >> 16
        if opcode == END:
            return finish()
        if opcode != COMPUTE:
            return finish(UNKNOWN_COMMAND, tx_id)
        if not parameters_valid(h, w, k):
            return finish(INVALID_PARAMETERS, tx_id)
        samples: list[int] = []
        for index in range(h * w):
            beat = read()
            samples.append(signed_sample(beat.data))
            if beat.last and index != h * w - 1:
                return finish(EARLY_PAYLOAD_TLAST, tx_id)
            if not beat.last and index == h * w - 1:
                return finish(MISSING_PAYLOAD_TLAST, tx_id)
        # No response beat is emitted until the complete payload is validated.
        values = pool_scalar(samples, h, w, k)
        output.extend((Beat(tx_id), Beat((h // k) | ((w // k) << 16), True)))
        output.extend(Beat(value & 0xFFFF, index == len(values) - 1)
                      for index, value in enumerate(values))
