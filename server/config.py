"""환경설정 로드 모듈.

모든 민감 정보(API 키 등)는 코드에 하드코딩하지 않고 `.env` 에서만 읽는다.
`.env` 는 .gitignore 로 보호되어 git 에 올라가지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 프로젝트 루트의 .env 를 로드
load_dotenv()

# Gemini Live API 권장 오디오 포맷 (공식 문서 기준)
#   입력: 16kHz, mono, 16-bit PCM, little-endian
#   출력: 24kHz, mono, 16-bit PCM, little-endian
INPUT_SAMPLE_RATE = 16_000
INPUT_CHANNELS = 1
INPUT_DTYPE = "int16"  # 16-bit PCM

# 100ms 단위 청크 전송 권장 → 16000 * 0.1 = 1600 샘플
CHUNK_MS = 100
CHUNK_SAMPLES = INPUT_SAMPLE_RATE * CHUNK_MS // 1000


def _require(name: str) -> str:
    """필수 환경변수를 읽되, 없으면 명확한 에러로 실패(fail fast)."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"환경변수 {name} 가 설정되지 않았습니다. "
            f".env.example 을 복사해 .env 를 만들고 값을 채우세요."
        )
    return value


@dataclass(frozen=True)
class Settings:
    """불변(immutable) 설정 객체."""

    gemini_api_key: str
    model: str
    source_language: str
    target_language: str
    ws_host: str
    ws_port: int
    # 장치 인덱스(int) 또는 장치 이름(str). 비우면 시스템 기본 입력(None).
    audio_input_device: str | int | None

    @staticmethod
    def load() -> "Settings":
        return Settings(
            gemini_api_key=_require("GEMINI_API_KEY"),
            model=os.getenv("GEMINI_MODEL", "gemini-3.5-live-translate-preview"),
            source_language=os.getenv("SOURCE_LANGUAGE", "ko"),
            target_language=os.getenv("TARGET_LANGUAGE", "en"),
            ws_host=os.getenv("WS_HOST", "0.0.0.0"),
            ws_port=int(os.getenv("WS_PORT", "8000")),
            audio_input_device=_parse_device(os.getenv("AUDIO_INPUT_DEVICE", "")),
        )


def _parse_device(raw: str) -> str | int | None:
    """AUDIO_INPUT_DEVICE 값을 sounddevice 가 이해하는 형태로 변환.

    - 숫자면 장치 인덱스(int) 로  → 예: "2" -> 2
    - 그 외 문자열이면 장치 이름(str) 으로 → 예: "Vocaster Two USB"
    - 비어 있으면 None (시스템 기본 입력)
    """
    device = raw.strip()
    if not device:
        return None
    return int(device) if device.isdigit() else device
