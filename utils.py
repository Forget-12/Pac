import atexit
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import Optional

_PROVIDER = ["CPUExecutionProvider"]

# Dibuat lazy saat load_session()/SO pertama kali diakses. Dengan begitu
# modul ini (khususnya CaptchaError) bisa di-import tanpa onnxruntime.
_ort = None
_ort_lock = threading.Lock()
_executor = None
_executor_lock = threading.Lock()

onnx_semaphore = asyncio.Semaphore(1)


def _ensure_ort():
    global _ort, SO
    if _ort is not None:
        return _ort
    with _ort_lock:
        if _ort is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
            SO = options
            _ort = ort
    return _ort


def _get_executor():
    """Executor khusus 1 thread: inference ONNX tidak berebut dengan I/O."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onnx")
                atexit.register(_executor.shutdown, wait=False)
    return _executor


def __getattr__(name):
    # Tetap kompatibel dengan `from utils import SO` / `utils.SO`.
    if name == "SO":
        _ensure_ort()
        return globals()["SO"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def load_session(model_path):
    ort = _ensure_ort()
    return ort.InferenceSession(
        model_path,
        sess_options=SO,
        providers=_PROVIDER,
    )


async def run(session, inputs):
    loop = asyncio.get_running_loop()

    async with onnx_semaphore:
        return await loop.run_in_executor(_get_executor(), session.run, None, inputs)


@dataclass
class CaptchaError(Exception):
    usr: str = "ERROR_CAPTCHA_UNSOLVABLE"
    msg: str = "Solver failed to process this task."
    api: Optional[str] = None

    def to_client_dict(self) -> dict:
        return {"usr": self.usr, "msg": self.msg, "api": self.api}

    def to_log_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def unsolvable(cls, api_detail: str, custom_msg: str = None) -> 'CaptchaError':
        return cls(
            usr="ERROR_CAPTCHA_UNSOLVABLE",
            msg=custom_msg or "Solver failed to find a valid solution.",
            api=api_detail
        )

    @classmethod
    def badparams(cls, api_detail: str, custom_msg: str = None) -> 'CaptchaError':
        return cls(
            usr="ERROR_INVALID_TASK",
            msg=custom_msg or "Invalid input provided to the solver.",
            api=api_detail
        )

    @classmethod
    def from_exception(cls, e: Exception, custom_usr: str = None, custom_msg: str = None) -> 'CaptchaError':
        err_str = str(e)
        err_type = type(e).__name__

        if err_str.startswith("ERROR_CAPTCHA_UNSOLVABLE:"):
            return cls.unsolvable(err_str, custom_msg)
        elif err_str.startswith("ERROR_INVALID_TASK:"):
            return cls.badparams(err_str, custom_msg)
        else:
            return cls(
                usr=custom_usr or "ERROR_CAPTCHA_UNSOLVABLE",
                msg=custom_msg or "Internal processing error occurred.",
                api=f"{err_type}: {err_str}"
            )

    def __str__(self) -> str:
        return f"{self.usr}:{self.api}[{self.msg}]"
