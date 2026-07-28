"""운영자 명령 처리 — ws_server.py 에서 분리(모듈 분리 2단계).

WebSocket 으로 온 운영 명령(reset/set_style/set_languages/set_backend/
set_broadcast/set_device/set_script/set_gain)을 검증·쿨다운 후 실행하고
결과를 브로드캐스트한다. 전역 state·hub 를 공유하며, 실제 재구성은
orchestration 에 위임한다.
"""

from __future__ import annotations

import logging
import time

from app_state import state
from audio_input import input_devices
from constants import (
    BACKEND_COOLDOWN_SEC,
    COMMAND_COOLDOWN_SEC,
    MAX_SCRIPT_CHARS,
    SCRIPT_PATH,
    _COOLDOWN_COMMANDS,
)
from hub import hub
from orchestration import apply_languages, set_broadcast, switch_backend
from validation import _sanitize_languages, _sanitize_style

log = logging.getLogger("server")


def _cooldown_remaining(name: str) -> float:
    """쿨다운이 남아 있으면 남은 초, 아니면 0 (H-3).

    운영 명령을 연타하면 워커·세션이 반복 재시작되어 지연·과금이 급증한다.
    무해한 명령(reset, list_devices 등)은 대상에서 제외한다.
    """
    if name not in _COOLDOWN_COMMANDS:
        return 0.0
    window = BACKEND_COOLDOWN_SEC if name == "set_backend" else COMMAND_COOLDOWN_SEC
    last = state.last_command_at.get(name, 0.0)
    elapsed = time.monotonic() - last
    return max(0.0, window - elapsed)


async def _handle_command(cmd: dict) -> None:
    """운영자 화면에서 온 명령을 처리하고 결과를 전체에 브로드캐스트."""
    name = cmd.get("cmd")

    # 남용 방지: 같은 명령을 짧은 간격으로 반복하면 무시하고 운영자에게 알린다.
    remaining = _cooldown_remaining(name)
    if remaining > 0:
        await hub.broadcast(
            {
                "type": "command_throttled",
                "cmd": name,
                "retry_after": round(remaining, 1),
            }
        )
        return
    if name in _COOLDOWN_COMMANDS:
        state.last_command_at[name] = time.monotonic()

    if name == "reset":
        state.reset_all()
        await hub.broadcast({"type": "reset"})
    elif name == "set_output":
        state.output_enabled = bool(cmd.get("enabled", True))
        await hub.broadcast({"type": "output_state", "enabled": state.output_enabled})
    elif name == "set_style":
        # 화이트리스트 검증(M-2): 허용된 키·타입·범위만 반영한다.
        incoming = _sanitize_style(cmd.get("style"))
        if incoming:
            state.style = {**state.style, **incoming}
            await hub.broadcast({"type": "style", "style": state.style})
    elif name == "set_languages":
        async with state.reconfig_lock:   # 재구성 동시 실행 방지
            languages = _sanitize_languages(cmd.get("languages"))
            await apply_languages(languages)
            await hub.broadcast({"type": "reset"})
            await hub.broadcast({"type": "layout", "layout": state.layout()})
    elif name == "set_broadcast":
        async with state.reconfig_lock:
            await set_broadcast(bool(cmd.get("active", True)))
    elif name == "set_backend":
        async with state.reconfig_lock:
            await switch_backend(cmd.get("backend", ""))
    elif name == "set_device":
        async with state.reconfig_lock:
            await _switch_device(cmd.get("device"))
    elif name == "list_devices":
        await hub.broadcast(
            {
                "type": "device_list",
                "devices": input_devices(),
                "device_error": state.capture.error if state.capture else None,
                "current": state.capture.current_device if state.capture else None,
            }
        )
    elif name == "set_script":
        await _set_script(cmd.get("text", ""))
    elif name == "set_gain":
        await _set_gain(cmd.get("gain"))


async def _set_gain(value) -> None:  # noqa: ANN001
    """입력 게인(소프트웨어 증폭)을 설정하고 결과를 브로드캐스트.

    슬라이더 드래그로 자주 오므로 쿨다운 대상이 아니다(무해).
    """
    if state.capture is None:
        return
    try:
        gain = float(value)
    except (TypeError, ValueError):
        return
    applied = state.capture.set_gain(gain)
    await hub.broadcast({"type": "gain_state", "gain": applied})


async def _set_script(text: str) -> None:
    """설교 원고를 설정 — 교정 용어 추출 + 저장 + 상태 전파."""
    if not isinstance(text, str):
        text = ""
    # 길이 상한(H-4): 과도한 원고로 메모리·디스크·교정 연산이 폭증하는 것을 막는다.
    if len(text) > MAX_SCRIPT_CHARS:
        log.warning(
            "원고가 상한을 초과해 잘라 적용합니다 (%d > %d자)",
            len(text),
            MAX_SCRIPT_CHARS,
        )
        text = text[:MAX_SCRIPT_CHARS]
        await hub.broadcast(
            {"type": "script_truncated", "limit": MAX_SCRIPT_CHARS}
        )
    n = state.script.set_script(text)
    try:
        SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCRIPT_PATH.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("원고 저장 실패(무시): %s", exc)
    log.info("설교 원고 적용 — 교정 용어 %d개", n)
    await hub.broadcast(
        {"type": "script_state", "terms": n, "chars": len(text)}
    )


async def _switch_device(device) -> None:  # noqa: ANN001
    """오디오 입력 장치를 교체하고 결과를 브로드캐스트."""
    if state.capture is None:
        return
    if isinstance(device, str) and device.isdigit():
        device = int(device)
    try:
        state.capture.set_device(device)   # 성공하면 capture.error 가 해제된다
        await hub.broadcast(
            {
                "type": "device_state",
                "current": state.capture.current_device,
                "device_error": state.capture.error,   # 복구되면 None → 배너 해제
            }
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("장치 전환 실패: %s", exc)
        await hub.broadcast({"type": "device_error", "message": str(exc)})
