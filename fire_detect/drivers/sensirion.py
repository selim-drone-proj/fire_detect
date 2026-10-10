"""
sensirion.py - Sensirion 센서(SGP30, SGP41, SHT31) 공통: CRC-8 과 16비트 워드 묶음 (공통 파일: odor_drone, fire_detect)

Sensirion 은 16비트 값 하나(2 B)마다 CRC 1 B 를 붙인다.
CRC-8: 다항식 0x31 (x^8 + x^5 + x^4 + 1), 초기값 0xFF, 반사 없음, 최종 XOR 없음.
확인값: crc8(b"\\xBE\\xEF") == 0x92 (데이터시트 예시)
"""
from __future__ import annotations


def crc8(data: bytes) -> int:
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


class CrcError(IOError):
    """센서가 보낸 CRC 가 맞지 않음 (배선 불량, 잡음, 전원 문제)"""


def pack_words(*words: int) -> bytes:
    """[w0, w1, ...] -> w0_hi w0_lo crc w1_hi w1_lo crc ..."""
    out = bytearray()
    for w in words:
        two = bytes([(w >> 8) & 0xFF, w & 0xFF])
        out += two + bytes([crc8(two)])
    return bytes(out)


def unpack_words(raw: bytes) -> list[int]:
    """3 B 씩 끊어 CRC 확인 후 16비트 값 목록. 틀리면 CrcError"""
    if len(raw) % 3:
        raise CrcError(f"길이가 3 의 배수가 아님: {len(raw)}")
    out = []
    for i in range(0, len(raw), 3):
        two, c = raw[i:i + 2], raw[i + 2]
        if crc8(two) != c:
            raise CrcError(f"CRC 불일치 (워드 {i // 3}: {two.hex()} crc {c:02x}, 계산 {crc8(two):02x})")
        out.append((two[0] << 8) | two[1])
    return out
