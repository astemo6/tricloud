"""后台任务系统：线程池 + SQLite 任务表，支持日志流、停止请求、重启恢复。"""
import concurrent.futures
import threading
import time
import traceback
import uuid

from . import config, db


class JobCtx:
    """传给任务函数的上下文：记日志、查停止、写结果。"""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def log(self, message: str) -> None:
        db.job_append_log(self.job_id, message)

    def should_stop(self) -> bool:
        job = db.job_get(self.job_id)
        return (job or {}).get("status") == "stop_requested"

    def set_result(self, result: str) -> None:
        db.job_update(self.job_id, result=result)


_executor: concurrent.futures.ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=config.JOB_WORKERS, thread_name_prefix="job"
            )
        return _executor


def _run_job(job_id: str, func, *args, **kwargs) -> None:
    ctx = JobCtx(job_id)
    db.job_update(job_id, status="running")
    try:
        result = func(ctx, *args, **kwargs)
        job = db.job_get(job_id)
        if job and job["status"] == "stop_requested":
            db.job_update(job_id, status="stopped", finished_at=time.time())
            ctx.log("任务已被手动停止")
        else:
            db.job_update(
                job_id,
                status="success",
                result=result or "",
                finished_at=time.time(),
            )
            ctx.log("任务完成")
    except Exception as e:  # noqa: BLE001 - 任务异常必须落库，不能抛到线程池外
        db.job_update(
            job_id,
            status="failed",
            result=f"失败: {e}",
            finished_at=time.time(),
        )
        ctx.log(f"任务失败: {e}")
        ctx.log(traceback.format_exc(limit=5))
    finally:
        # Telegram 推送（未配置则静默跳过）
        try:
            from . import tg as _tg
            _tg.notify_job_finished(db.job_get(job_id) or {})
        except Exception:  # noqa: BLE001, S110 - 推送失败不影响任务本身
            pass


def submit(job_type: str, provider: str, account_id: int | None, title: str, func, *args, **kwargs) -> str:
    job_id = uuid.uuid4().hex[:12]
    db.job_create(job_id, job_type, provider, account_id, title)
    _get_executor().submit(_run_job, job_id, func, *args, **kwargs)
    return job_id


def request_stop(job_id: str) -> bool:
    job = db.job_get(job_id)
    if not job or job["status"] not in ("queued", "running"):
        return False
    db.job_update(job_id, status="stop_requested")
    db.job_append_log(job_id, "收到停止请求，任务将在当前步骤后停止…")
    return True
