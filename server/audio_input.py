"""오디오 입력 캡처 모듈.

교회 믹서 → 오디오 인터페이스 → 컴퓨터로 들어온 신호를
Gemini Live API 가 요구하는 16kHz / mono / 16-bit PCM 으로 캡처해
asyncio 큐로 100ms 청크를 흘려보낸다.

단독 실행 시 입력 장치 목록 확인 / 레벨 모니터 기능 제공:
    python server/audio_input.py --list      # 장치 목록
    python server/audio_input.py --monitor   # 입력 레벨 확인
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import numpy as np
import sounddevice as sd

from config import (
    CHUNK_SAMPLES,
    INPUT_CHANNELS,
    INPUT_DTYPE,
    INPUT_SAMPLE_RATE,
)


class AudioCapture:
    """sounddevice 입력 스트림을 asyncio 큐에 연결한다.

    sounddevice 콜백은 별도 스레드에서 호출되므로,
    스레드-세이프하게 메인 이벤트 루프의 큐로 전달한다.
    """

    def __init__(self, device: str | int | None = None, max_queue: int = 50) -> None:
        self._device = device
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_queue)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            # 오버플로우/언더런 등은 무시하지 않고 표준에러로 알린다.
            print(f"[audio] 입력 상태 경고: {status}", file=sys.stderr)
        # indata: int16 mono → 그대로 PCM 바이트로 변환
        pcm_bytes = bytes(indata)
        if self._loop is None:
            return
        # 콜백은 PortAudio 스레드에서 실행되므로, 실제 큐 적재는 이벤트 루프
        # 스레드 안에서 수행해야 QueueFull 을 안전하게 처리할 수 있다.
        # (call_soon_threadsafe 는 예약만 하고 반환 → 여기서 except 로는 못 잡는다)
        self._loop.call_soon_threadsafe(self._enqueue, pcm_bytes)

    def _enqueue(self, pcm_bytes: bytes) -> None:
        """이벤트 루프 스레드에서 실행 — 큐가 차면 가장 오래된 청크를 버린다.

        오디오는 최신이 더 중요하므로 drop-oldest 로 처리한다(최신을 버리면
        자막에 더 큰 공백이 생긴다)."""
        try:
            self._queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()       # 가장 오래된 것 제거
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(pcm_bytes)
            except asyncio.QueueFull:
                pass

    def _open_stream(self, device: str | int | None) -> None:
        stream = sd.InputStream(
            samplerate=INPUT_SAMPLE_RATE,
            channels=INPUT_CHANNELS,
            dtype=INPUT_DTYPE,
            blocksize=CHUNK_SAMPLES,  # 100ms 청크
            device=device,
            callback=self._callback,
        )
        stream.start()
        self._stream = stream
        self._device = device

    def _close_stream(self) -> None:
        if self._stream is not None:
            # stop() 은 진행 중인 콜백이 끝날 때까지 블록 → 스트림 교체가 안전.
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def __aenter__(self) -> "AudioCapture":
        self._loop = asyncio.get_running_loop()
        self._open_stream(self._device)
        return self

    async def __aexit__(self, *exc) -> None:  # noqa: ANN002
        self._close_stream()

    def set_device(self, device: str | int | None) -> None:
        """입력 스트림만 교체. 큐(=하류 소비자)는 유지되어 세션이 끊기지 않는다."""
        self._close_stream()
        self._open_stream(device)
        print(f"[audio] 입력 장치 전환 → {device}")

    @property
    def current_device(self) -> str | int | None:
        return self._device

    async def chunks(self):
        """100ms PCM 청크를 비동기로 yield."""
        while True:
            yield await self._queue.get()


async def queue_chunks(queue: "asyncio.Queue[bytes]"):
    """asyncio 큐를 오디오 청크 비동기 제너레이터로 변환."""
    while True:
        yield await queue.get()


class AudioFanout:
    """하나의 오디오 입력을 여러 구독자(세션)에게 복제해 전달한다.

    언어별로 별도 Live 세션을 동시에 돌릴 때, 같은 마이크 입력을
    각 세션에 똑같이 흘려보내기 위해 사용한다.
    """

    def __init__(self, capture: AudioCapture, max_queue: int = 50) -> None:
        self._capture = capture
        self._max_queue = max_queue
        self._subscribers: set[asyncio.Queue[bytes]] = set()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        async for chunk in self._capture.chunks():
            for queue in list(self._subscribers):
                try:
                    queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass  # 느린 구독자는 해당 청크만 건너뛴다

    def subscribe(self) -> "asyncio.Queue[bytes]":
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[bytes]") -> None:
        self._subscribers.discard(queue)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def list_devices() -> None:
    print(sd.query_devices())


def input_devices() -> list[dict]:
    """입력 가능한(채널>0) 장치만 골라 구조화해 반환 (운영자 UI용)."""
    devices = []
    for index, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            devices.append(
                {
                    "index": index,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                }
            )
    return devices


def monitor_level(device: str | int | None = None, seconds: float = 10.0) -> None:
    """입력 레벨(RMS)을 콘솔에 막대로 표시 — 믹서 연결 점검용."""
    print(f"{seconds}초간 입력 레벨 모니터링… (Ctrl+C 로 중단)")

    def cb(indata, frames, time_info, status):  # noqa: ANN001
        rms = float(np.sqrt(np.mean(np.square(indata.astype(np.float32)))))
        level = min(int(rms / 500), 50)
        print("\r[" + "#" * level + " " * (50 - level) + f"] {rms:7.0f}", end="")

    with sd.InputStream(
        samplerate=INPUT_SAMPLE_RATE,
        channels=INPUT_CHANNELS,
        dtype=INPUT_DTYPE,
        device=device,
        callback=cb,
    ):
        sd.sleep(int(seconds * 1000))
    print("\n완료.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="오디오 입력 점검 도구")
    parser.add_argument("--list", action="store_true", help="입력 장치 목록 표시")
    parser.add_argument("--monitor", action="store_true", help="입력 레벨 모니터")
    parser.add_argument("--device", default=None, help="장치 이름 또는 인덱스")
    args = parser.parse_args()

    dev: str | int | None = args.device
    if dev is not None and dev.isdigit():
        dev = int(dev)

    if args.list:
        list_devices()
    elif args.monitor:
        monitor_level(dev)
    else:
        parser.print_help()
