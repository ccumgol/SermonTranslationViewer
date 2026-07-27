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
import logging
import math

import numpy as np
import sounddevice as sd

from config import (
    CHUNK_SAMPLES,
    INPUT_CHANNELS,
    INPUT_DTYPE,
    INPUT_SAMPLE_RATE,
)

log = logging.getLogger("audio")


# 16-bit PCM 최대 진폭 — RMS 를 0.0~1.0 로 정규화할 때 쓴다.
INT16_FULL_SCALE = 32768.0
# 게이지 하한. 이보다 조용하면 '무음'으로 표시한다.
SILENCE_DBFS = -60.0
# 소프트웨어 입력 게인(배율) 허용 범위. 1.0=증폭 없음.
# 시스템/믹서 볼륨을 못 올리는 상황에서 낮은 신호를 앱에서 증폭해 STT 임계값을 넘긴다.
MIN_GAIN = 1.0
MAX_GAIN = 8.0


def rms_to_dbfs(rms: float) -> float:
    """RMS(0.0~1.0)를 dBFS 로 변환. 무음은 SILENCE_DBFS 로 바닥을 둔다.

    사람 귀는 로그 스케일이라, 선형 RMS 를 그대로 막대로 그리면 보통의 말소리도
    거의 왼쪽 끝에 붙어 보인다.
    """
    if rms <= 0.0:
        return SILENCE_DBFS
    return max(SILENCE_DBFS, 20.0 * math.log10(rms))


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
        # 입력 레벨(0.0~1.0 RMS) 피크 — 운영자 화면 게이지용.
        # 오디오 콜백 스레드가 쓰고 이벤트 루프가 읽지만, float 대입/읽기는
        # GIL 하에서 원자적이라 락이 필요 없다(값이 조금 늦게 반영돼도 무해).
        self._peak_level = 0.0
        # 소프트웨어 입력 게인(배율). 1.0=증폭 없음. 콜백 스레드가 읽고 루프가 씀.
        self._gain = 1.0
        # 입력 장치를 못 연 경우의 사용자 안내 문구(정상이면 None).
        # 운영자 화면에 띄워, 장치를 꽂고 '목록 새로고침 → 선택'으로 복구하게 한다.
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        """입력 장치 문제 안내(없으면 None)."""
        return self._error

    def _apply_gain(self, indata):  # noqa: ANN001, ANN201
        """입력 신호에 게인을 곱하고 int16 범위로 클리핑한다. 1.0 이면 그대로 반환."""
        if self._gain == 1.0:
            return indata
        amplified = np.asarray(indata, dtype=np.float32) * self._gain
        np.clip(amplified, -INT16_FULL_SCALE, INT16_FULL_SCALE - 1, out=amplified)
        return amplified.astype(np.int16)

    def set_gain(self, gain: float) -> float:
        """입력 게인을 설정(범위로 클램프)하고 실제 적용된 값을 반환."""
        self._gain = max(MIN_GAIN, min(float(gain), MAX_GAIN))
        return self._gain

    @property
    def gain(self) -> float:
        return self._gain

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            # 오버플로우/언더런 등은 무시하지 않고 표준에러로 알린다.
            log.warning("입력 상태 경고: %s", status)
        # 게인을 먼저 적용해 레벨 게이지·전사(fanout)에 동일하게 반영한다.
        indata = self._apply_gain(indata)
        self._track_level(indata)
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

    def _track_level(self, indata) -> None:  # noqa: ANN001
        """이번 청크의 RMS 를 계산해 피크로 누적(오디오 콜백 스레드에서 실행)."""
        try:
            samples = np.asarray(indata, dtype=np.float32)
            if samples.size == 0:
                return
            rms = float(np.sqrt(np.mean(np.square(samples)))) / INT16_FULL_SCALE
        except Exception:  # noqa: BLE001
            return  # 레벨 표시는 부가 기능 — 실패해도 오디오 흐름을 막지 않는다
        if rms > self._peak_level:
            self._peak_level = rms

    def pop_level(self) -> float:
        """마지막 호출 이후의 피크 레벨(0.0~1.0)을 반환하고 초기화한다.

        피크를 쓰는 이유: 평균을 내면 짧은 말소리가 무음에 묻혀 게이지가
        거의 움직이지 않는다.
        """
        peak = self._peak_level
        self._peak_level = 0.0
        return peak

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
        self._error = None   # 열렸으면 이전 오류 표시를 지운다(복구 완료)

    def _close_stream(self) -> None:
        # 장치를 바꾸면 이전 장치의 레벨이 남아 '신호 있음'으로 잘못 보이지 않게 한다.
        self._peak_level = 0.0
        if self._stream is not None:
            # stop() 은 진행 중인 콜백이 끝날 때까지 블록 → 스트림 교체가 안전.
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def __aenter__(self) -> "AudioCapture":
        """입력 스트림을 연다. **실패해도 예외를 올리지 않는다.**

        여기서 예외가 나가면 파이프라인 전체가 죽어 자막이 영영 나오지 않는다.
        그런데 서버는 200 OK 로 응답하고 운영자 화면도 정상으로 보여서, 원인을
        찾을 방법이 없다(실제로 겪음: `.env` 의 Vocaster 가 미연결이라 조용히 죽음).

        그래서 지정 장치가 안 열리면 **기본 장치로 대체**하고, 그것도 안 되면
        오류만 기록한 채 살아 있는다. 운영자는 장치를 꽂은 뒤 화면에서
        '목록 새로고침 → 선택'으로 복구할 수 있다.
        """
        self._loop = asyncio.get_running_loop()
        requested = self._device
        try:
            self._open_stream(requested)
            return self
        except Exception as exc:  # noqa: BLE001
            log.warning("지정한 입력 장치를 열 수 없습니다 (%s): %s", requested, exc)

        if requested is not None:
            try:
                self._open_stream(None)   # 기본 입력 장치로 대체
                self._error = (
                    f"지정한 입력 장치({requested})를 찾을 수 없어 "
                    "기본 장치로 대체했습니다. 장치를 연결한 뒤 목록을 새로고침하세요."
                )
                log.warning("기본 입력 장치로 대체했습니다 — 운영자 화면에서 바꿀 수 있습니다")
                return self
            except Exception as exc:  # noqa: BLE001
                log.error("기본 입력 장치도 열 수 없습니다: %s", exc)

        self._error = (
            f"입력 장치를 열 수 없습니다({requested}). "
            "장치를 연결한 뒤 운영자 화면에서 목록을 새로고침하고 선택하세요."
        )
        return self

    async def __aexit__(self, *exc) -> None:  # noqa: ANN002
        self._close_stream()

    def set_device(self, device: str | int | None) -> None:
        """입력 스트림만 교체. 큐(=하류 소비자)는 유지되어 세션이 끊기지 않는다."""
        self._close_stream()
        self._open_stream(device)
        log.info("입력 장치 전환 → %s", device)

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
            # 가상 오디오 장치(BlackHole 등)는 '컴퓨터에서 나는 소리'를 캡처할 수
            # 있으므로 운영자가 알아볼 수 있게 표시한다(유튜브 영상 번역 등에 사용).
            lowered = dev["name"].lower()
            is_loopback = any(
                key in lowered
                for key in ("blackhole", "loopback", "soundflower", "vb-audio",
                            "virtual", "aggregate", "stereo mix", "what u hear")
            )
            devices.append(
                {
                    "index": index,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "system_audio": is_loopback,
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
