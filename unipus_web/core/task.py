"""任务状态机。

并发模型：
- 每个任务一个守护线程；
- 暂停/恢复/冷却统一走 Condition；
- 停止用 stop_event + generation 双保险，防止旧线程在重启后继续写状态或提交。
"""

from __future__ import annotations

import logging
import random
import threading
import time
from enum import Enum
from typing import Callable, Protocol

from ..api.errors import ApiError, AuthError, NetworkError, TaskStopped, UnipusError
from .duration import (
    CourseDurationClient,
    DurationTarget,
    build_duration_targets,
)
from ..models import (
    Course,
    CourseResource,
    TaskSnapshot,
    User,
    as_str,
    lenient_obj,
    validate_duration_param,
)

logger = logging.getLogger(__name__)


class Status(str, Enum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    NEED_OPERATION = "NEED_OPERATION"
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class UserOperation(str, Enum):
    CHOOSE_COURSE = "CHOOSE_COURSE"
    CHOOSE_PRACTICE = "CHOOSE_PRACTICE"
    CHOOSE_DURATION = "CHOOSE_DURATION"


class TaskControl(Protocol):
    def checkpoint(self) -> None: ...
    def set_description(self, text: str) -> None: ...
    def set_progress(self, completed: int, total: int) -> None: ...
    def set_status(self, status: Status) -> None: ...
    def wait_for_cooldown(self, ms: int, waiting_desc: str, after_desc: str) -> None: ...
    def suspend(self) -> None: ...
    def warn(self, message: str) -> None: ...
    @property
    def stop_requested(self) -> bool: ...
    @property
    def user(self) -> User | None: ...


class Task:
    def __init__(
        self,
        task_id: str,
        username: str,
        password: str | None,
        *,
        client_factory: Callable[[str], object],
        on_change: Callable[[dict], None],
        on_warning: Callable[[str], None],
        on_error: Callable[[str], None],
        credential_id: str | None = None,
        login_session: dict | None = None,
        on_login_session: Callable[[dict], None] | None = None,
        allow_multi_question: bool = True,
        duration_client_factory: Callable[[], CourseDurationClient] | None = None,
        proxy: str | None = None,
    ) -> None:
        self.task_id = task_id
        self.username = username
        self.password = password
        self.credential_id = credential_id
        self.login_session = login_session
        self.allow_multi_question = allow_multi_question
        self._duration_client_factory = duration_client_factory
        self.proxy = proxy
        self._on_login_session = on_login_session

        self._client_factory = client_factory
        self._on_change = on_change
        self._on_warning = on_warning
        self._on_error = on_error

        self.client = None
        self.user: User | None = None
        self.course_list: list[Course] = []
        self.current_course: Course | None = None
        self.current_resource: CourseResource | None = None

        self.name = ""
        self.status = Status.INITIALIZING
        self.description = "正在初始化..."
        self.completed = 0
        self.total = 0
        self.user_operation: UserOperation | None = None
        self.warning: str | None = None
        self.error: str | None = None

        # 任务方式：required = 必修，catalog = 全目录自选，duration = 学习时长
        self.practice_mode = "required"
        # 每个练习的时长参数：int=固定秒数；tuple=(最小值, 最大值) 随机
        self.duration_param: int | tuple[int, int] = 0
        self.duration_targets: list[DurationTarget] = []
        # 并行计时：可同时挂多个目标，各自独立连接，总耗时≈单项最长时长
        self.selected_duration_targets: list[DurationTarget] = []
        self.catalog: dict | None = None
        self.selected_task_ids: list[str] = []

        self._cond = threading.Condition()
        self._stop_event = threading.Event()
        self._generation = 0
        self._worker: threading.Thread | None = None
        self._awaiting_user = False
        self._user_op_done = False
        self._removed = False
        self._tls = threading.local()

    # ------------------------------------------------------------ 生命周期

    @property
    def generation(self) -> int:
        return self._generation

    def initialize(self) -> None:
        """后台线程调用：登录并拉取用户信息。"""
        try:
            self.client = self._client_factory(self.task_id)
            restored_session = self.login_session is not None
            try:
                if self.login_session is None:
                    rs = self.client.login(self.username, self.password or "")
                else:
                    rs = self.client.restore_login_session(self.login_session)
                info = self.client.get_user_info()
            except (ApiError, AuthError):
                if not restored_session:
                    raise
                rs = self.client.login(self.username, self.password or "")
                info = self.client.get_user_info()
            self.user = User(
                username=as_str(rs.get("username"), self.username),
                jwt=as_str(rs.get("jwt")),
                open_id=as_str(rs.get("openid")),
            )
            info = self.client.get_user_info()
            user_info = lenient_obj(lenient_obj(info.get("value")).get("userInfo"))
            self.user.name = as_str(user_info.get("name"))
            self.user.school_name = as_str(user_info.get("schName"))
            self.user.app_user_id = as_str(user_info.get("appUserId"))
            self.user.sso_id = as_str(user_info.get("ssoId"))
            self.name = " - ".join(
                part for part in (self.user.school_name, self.user.name) if part
            ) or self.username
            if self._on_login_session is not None:
                try:
                    self._on_login_session(self.client.export_login_session())
                except Exception:
                    logger.debug(
                        "Task %s could not save its login session.",
                        self.task_id,
                        exc_info=True,
                    )
            self._update(status=Status.READY, description="登录成功，未启动")
        except AuthError as exc:
            self._fail(str(exc))
        except NetworkError as exc:
            self._fail(f"网络错误：{exc}")
        except Exception as exc:  # 未知异常也要让 UI 看到
            logger.exception("Task %s initialization failed", self.task_id)
            self._fail(f"任务初始化失败：{type(exc).__name__} - {exc}")

    def start(self, *, practice_mode: str = "required") -> bool:
        with self._cond:
            if self.status is not Status.READY:
                return False
            if self._worker is not None and self._worker.is_alive():
                return False
            self.practice_mode = practice_mode
            self.catalog = None
            self.selected_task_ids = []
            self.duration_targets = []
            self.selected_duration_targets = []
            if practice_mode != "duration":
                self.duration_param = 0
            self._generation += 1
            generation = self._generation
            self._stop_event.clear()
            self.status = Status.RUNNING
            self.description = "正在启动任务..."
            self.error = None
            self.warning = None
            self._cond.notify_all()

        self._emit_change()
        self._worker = threading.Thread(
            target=self._run,
            args=(generation,),
            name=self.task_id,
            daemon=True,
        )
        self._worker.start()
        return True

    def start_catalog(self) -> bool:
        """以全目录自选方式开始；进入选择前会先加载目录。"""
        return self.start(practice_mode="catalog")

    def start_duration(
        self, *, duration_param: int | tuple[int, int] | None = None
    ) -> bool:
        """以学习时长方式开始。

        duration_param 可在启动时给定（固定秒数或 (下限, 上限) 随机范围），
        也可以留空，在选定计时内容时通过 choose_duration 提供。
        """
        if duration_param is not None:
            validate_duration_param(duration_param)
        with self._cond:
            if self.status is not Status.READY:
                return False
            self.duration_param = duration_param if duration_param is not None else 0
        return self.start(practice_mode="duration")

    @staticmethod
    def _generate_learning_time(param: int | tuple[int, int]) -> int:
        """固定秒数直接返回；(下限, 上限) 则在区间内随机取一个整数秒。"""
        if isinstance(param, tuple):
            return random.randint(param[0], param[1])
        return int(param)

    def _run(self, generation: int) -> None:
        self._tls.generation = generation
        try:
            summary = self._prepare_and_learn(generation)
            if self._is_stale(generation) or self._stop_event.is_set():
                return
            if self.practice_mode == "duration":
                description = "目标学习时长已达到。"
            elif summary is not None and summary.submitted_tasks == 0 and summary.skipped_tasks > 0:
                description = "任务已完成（部分题型被跳过，详情见日志）"
            else:
                description = "任务已完成。"
            self._update(
                gen=generation,
                status=Status.COMPLETED,
                description=description,
            )
        except TaskStopped:
            logger.info("Task %s stopped by user.", self.task_id)
        except (AuthError, NetworkError, UnipusError) as exc:
            if self._is_stale(generation) or self._stop_event.is_set():
                return
            message = str(exc)
            self._update(gen=generation, status=Status.ERROR, description=message)
            self._emit_error(message)
        except Exception as exc:
            if self._is_stale(generation) or self._stop_event.is_set():
                return
            logger.exception("Task %s failed", self.task_id)
            message = f"发生未捕获异常：{type(exc).__name__} - {exc}"
            self._update(gen=generation, status=Status.ERROR, description=message)
            self._emit_error(message)
        finally:
            try:
                del self._tls.generation
            except AttributeError:
                pass

    def _prepare_and_learn(self, generation: int):
        self._update(gen=generation, description="正在获取课程列表...")
        data = self.client.get_course_list()
        raw_courses = lenient_obj(data.get("value")).get("courseList")
        courses = (
            [Course.from_json(item) for item in raw_courses]
            if isinstance(raw_courses, list)
            else []
        )
        if not courses:
            raise UnipusError("未找到可学习的课程，请检查账号信息。")
        self.course_list = courses

        self._select_course(generation, courses)

        course = self.current_course
        resource = self.current_resource
        if resource is None:
            raise UnipusError("未选择教程。")
        if course is None:
            raise UnipusError("未选择课程。")

        now_ms = int(time.time() * 1000)
        if not (course.start_time < now_ms < course.end_time):
            raise UnipusError("课程已结束，无法学习。")

        self.name = f"{course.name} - {resource.name}"
        self._update(
            gen=generation,
            completed=resource.finish_point_num,
            total=resource.total_point_num,
        )

        # 延迟导入，避免 Task 与 Learn 的循环依赖
        from .learn import learn_course

        if self.practice_mode == "duration":
            return self._prepare_and_learn_duration(generation, resource)

        if self.practice_mode == "catalog":
            return self._prepare_and_practice_catalog(generation, resource)

        return learn_course(
            self,
            self.client,
            resource,
            allow_multi_question=self.allow_multi_question,
        )

    def _prepare_and_practice_catalog(self, generation: int, resource):
        from .learn import build_catalog, learn_selected_tasks, load_course_context

        self._update(gen=generation, description="正在加载题目目录")
        context = load_course_context(self, self.client, resource)
        result = build_catalog(
            self,
            self.client,
            context,
            allow_multi_question=self.allow_multi_question,
        )
        # 旧线程不能在检查 generation 之前覆盖新任务的目录
        self._set_catalog_if_current(generation, result["tree"])

        self._begin_user_operation(
            UserOperation.CHOOSE_PRACTICE, generation=generation
        )
        self.wait_for_user_operation()
        if self._stop_event.is_set() or self._is_stale(generation):
            raise TaskStopped()

        self._update(gen=generation, description="正在刷选中的题目")
        return learn_selected_tasks(
            self,
            self.client,
            context,
            list(self.selected_task_ids),
            allow_multi_question=self.allow_multi_question,
        )

    def _prepare_and_learn_duration(self, generation: int, resource):
        from .learn import load_course_context

        self._update(gen=generation, description="正在读取课程计时目录")
        context = load_course_context(self, self.client, resource)
        targets = build_duration_targets(context.course)
        if not targets:
            raise UnipusError("该教程没有可计时的学习内容")

        with self._cond:
            if generation != self._generation or self._stop_event.is_set():
                raise TaskStopped()
            self.duration_targets = targets
            if len(targets) == 1:
                self.selected_duration_targets = [targets[0]]
            else:
                self.selected_duration_targets = []

        if len(targets) > 1:
            self._begin_user_operation(
                UserOperation.CHOOSE_DURATION, generation=generation
            )
            self.wait_for_user_operation()
            if self._stop_event.is_set() or self._is_stale(generation):
                raise TaskStopped()

        targets = list(self.selected_duration_targets)
        if not targets:
            raise UnipusError("未选择计时内容")
        if not self.duration_param:
            raise UnipusError("未设置每个练习的学习时长")
        return self._learn_duration(generation, context, targets, self.duration_param)

    def _learn_duration(
        self,
        generation: int,
        context,
        targets: list[DurationTarget],
        duration_param: int | tuple[int, int],
    ):
        """并行累计多个学习内容的时长。

        每个目标各自建立一条计时连接并独立计时，多条连接在时间线上重叠，
        因此总耗时约等于最长单项时长，而不是各项相加。duration_param 为
        固定秒数或 (下限, 上限) 随机范围时，每个练习各自取一个时长，更
        像真人学习。任意一条连接中断即整体失败。
        """
        user = self.user
        if user is None or not user.open_id:
            raise UnipusError("尚未登录，无法开始学习时长任务。")

        factory = self._duration_client_factory or (
            lambda: CourseDurationClient(user.open_id, proxy=self.proxy)
        )
        self.checkpoint()
        # 每个练习分配一个时长（固定或范围内随机）
        per_target_seconds = [
            self._generate_learning_time(duration_param) for _ in targets
        ]
        max_seconds = max(per_target_seconds)
        label = targets[0].name if len(targets) == 1 else f"{len(targets)} 个学习内容"

        # 每个目标一个工作者线程；进度取所有目标已累计秒数的最大值，等最长的那条
        # 结束才到 100%，避免某条先结束让进度条提前满格。
        state_lock = threading.Lock()
        elapsed = [0.0] * len(targets)
        failure: Exception | None = None

        def publish(description: str) -> None:
            with state_lock:
                done = max(elapsed)
            self._update(
                gen=generation,
                completed=min(int(done), max_seconds),
                total=max_seconds,
                description=description,
            )

        def run_target(index: int) -> None:
            nonlocal failure
            target = targets[index]
            target_seconds = per_target_seconds[index]
            client = factory()
            completed = 0
            segment_start: float | None = None
            try:
                client.connect()
                client.start(target, context.course_instance_id, context.resource_id)
                segment_start = time.monotonic()
                last_publish = time.monotonic()
                while True:
                    with self._cond:
                        if self._stop_event.is_set() or self._is_stale(generation):
                            raise TaskStopped()
                        paused = self.status is Status.PAUSED
                    now = time.monotonic()

                    if paused:
                        if segment_start is not None:
                            completed += max(0, now - segment_start)
                            segment_start = None
                            client.stop()
                        with self._cond:
                            while self.status is Status.PAUSED:
                                if self._stop_event.is_set() or self._is_stale(
                                    generation
                                ):
                                    raise TaskStopped()
                                self._cond.wait(0.2)
                        client.start(
                            target, context.course_instance_id, context.resource_id
                        )
                        segment_start = time.monotonic()
                        continue

                    if not client.healthy:
                        raise NetworkError("计时连接中断，任务已停止")

                    if segment_start is not None:
                        current = completed + max(0, now - segment_start)
                        with state_lock:
                            elapsed[index] = current
                        if now - last_publish >= 1:
                            publish(f"正在累计学习时长：{label}")
                            last_publish = now
                        if current >= target_seconds:
                            client.stop()
                            completed = target_seconds
                            segment_start = None
                            break

                    time.sleep(0.05)
            except TaskStopped:
                raise
            except Exception as exc:  # 任一目标失败即整体失败
                with state_lock:
                    if failure is None:
                        failure = exc
            finally:
                if segment_start is not None:
                    try:
                        client.stop()
                    except Exception:
                        logger.warning(
                            "Task %s failed to send final duration stop.",
                            self.task_id,
                        )
                try:
                    client.close()
                except Exception:
                    logger.debug(
                        "Task %s duration socket cleanup failed.", self.task_id
                    )
                with state_lock:
                    elapsed[index] = completed

        self._update(
            gen=generation,
            completed=0,
            total=max_seconds,
            description=f"正在累计学习时长：{label}",
        )

        workers = []
        for index in range(len(targets)):
            worker = threading.Thread(
                target=run_target,
                args=(index,),
                name=f"duration-{targets[index].group_id}",
                daemon=True,
            )
            workers.append(worker)
            worker.start()
        # 主工作线程阻塞等待所有计时线程结束；停止/暂停由各线程自行检查
        for worker in workers:
            worker.join()

        if self._stop_event.is_set() or self._is_stale(generation):
            raise TaskStopped()
        if failure is not None:
            if isinstance(failure, (AuthError, NetworkError, UnipusError)):
                raise failure
            raise NetworkError(f"计时任务失败：{failure}")
        self._update(
            gen=generation,
            completed=max_seconds,
            total=max_seconds,
            description=f"学习时长已完成：{label}",
        )
        from .learn import LearnSummary

        return LearnSummary()

    def _select_course(self, generation: int, courses: list[Course]) -> None:
        if len(courses) == 1:
            course = courses[0]
            if len(course.resources) == 1:
                self.current_course = course
                self.current_resource = course.resources[0]
                return
            if not course.resources:
                raise UnipusError("该课程下没有可学习的教程。")

        self._begin_user_operation(generation=generation)
        self.wait_for_user_operation()
        if self._stop_event.is_set() or self._is_stale(generation):
            raise TaskStopped()

    # ------------------------------------------------------------ 用户交互

    def _set_catalog_if_current(self, generation: int, tree: dict) -> None:
        with self._cond:
            if generation != self._generation or self._stop_event.is_set():
                raise TaskStopped()
            self.catalog = tree

    def _begin_user_operation(
        self,
        operation: UserOperation = UserOperation.CHOOSE_COURSE,
        *,
        generation: int | None = None,
    ) -> None:
        with self._cond:
            if generation is not None and (
                generation != self._generation or self._stop_event.is_set()
            ):
                raise TaskStopped()
            self._awaiting_user = True
            self._user_op_done = False
            self.user_operation = operation
            # 用户在这之前已暂停时保留暂停状态，恢复后再回到选择界面
            if self.status is not Status.PAUSED:
                self.status = Status.NEED_OPERATION
            if operation is UserOperation.CHOOSE_COURSE:
                self.description = "请选择要学习的教程"
            elif operation is UserOperation.CHOOSE_PRACTICE:
                self.description = "请选择要刷的题目"
            else:
                self.description = "请选择要累计时长的学习内容"
            self._cond.notify_all()
        self._emit_change()

    def wait_for_user_operation(self) -> None:
        generation = self._current_generation()
        with self._cond:
            while not self._user_op_done:
                if self._stop_event.is_set() or (
                    generation is not None and generation != self._generation
                ):
                    raise TaskStopped()
                self._cond.wait(0.5)
            self._awaiting_user = False

    def choose_course(self, course: Course, resource: CourseResource) -> None:
        with self._cond:
            self.current_course = course
            self.current_resource = resource
            self.name = f"{course.name} - {resource.name}"
            self._user_op_done = True
            self.user_operation = None
            if self.status is Status.NEED_OPERATION:
                self.status = Status.RUNNING
                self.description = "已选择教程，继续学习"
            self._cond.notify_all()
        self._emit_change()

    def choose_duration(
        self,
        target_ids: str | list[str],
        duration_param: int | tuple[int, int] | None = None,
    ) -> None:
        """选定计时内容；可同时指定每个练习的时长（固定秒数或随机范围）。"""
        wanted = [target_ids] if isinstance(target_ids, str) else list(target_ids)
        wanted = [str(item) for item in wanted if str(item)]
        if not wanted:
            raise ValueError("必须选择计时内容")
        by_id = {item.group_id: item for item in self.duration_targets}
        targets: list[DurationTarget] = []
        for target_id in dict.fromkeys(wanted):   # 去重且保持顺序
            target = by_id.get(target_id)
            if target is None:
                raise ValueError("计时内容不存在")
            targets.append(target)
        if duration_param is not None:
            duration_param = validate_duration_param(duration_param)
        with self._cond:
            self.selected_duration_targets = targets
            if duration_param is not None:
                self.duration_param = duration_param
            self._user_op_done = True
            self.user_operation = None
            if self.status is Status.NEED_OPERATION:
                self.status = Status.RUNNING
                self.description = "已选择计时内容，继续刷时长"
            self._cond.notify_all()
        self._emit_change()

    def choose_practice(self, task_ids: list[str]) -> None:
        with self._cond:
            self.selected_task_ids = [
                str(task_id) for task_id in task_ids or [] if str(task_id)
            ]
            self._user_op_done = True
            self.user_operation = None
            if self.status is Status.NEED_OPERATION:
                self.status = Status.RUNNING
                self.description = "已选择题目，继续刷题"
            self._cond.notify_all()
        self._emit_change()

    # ------------------------------------------------------------ 控制接口

    def _ensure_current(self) -> None:
        """工作线程必须确认自己的 generation 仍是当前代。

        停止会递增 generation 并清除 stop_event；如果不校验 generation，
        旧线程在重启后会误以为没有被停止，从而与新线程并发提交。
        """
        generation = self._current_generation()
        if generation is not None and generation != self._generation:
            raise TaskStopped()

    def checkpoint(self) -> None:
        self._ensure_current()
        with self._cond:
            while True:
                self._ensure_current()
                if self._stop_event.is_set():
                    raise TaskStopped()
                if self.status is not Status.PAUSED:
                    return
                self._cond.wait(0.5)

    def wait_for_cooldown(
        self, ms: int, waiting_desc: str = "", after_desc: str = ""
    ) -> None:
        self._ensure_current()
        if ms <= 0:
            return
        deadline = time.monotonic() + ms / 1000.0
        with self._cond:
            self._ensure_current()
            if self._stop_event.is_set():
                return
            original = self.description
            self.status = Status.WAITING
            if waiting_desc:
                self.description = waiting_desc

            while True:
                self._ensure_current()
                if self._stop_event.is_set():
                    break
                if self.status is Status.PAUSED:
                    self._cond.wait(0.5)
                    continue
                if self.status is not Status.WAITING:
                    break
                now = time.monotonic()
                if now >= deadline:
                    break
                self._cond.wait(min(1.0, deadline - now))

            if not self._stop_event.is_set():
                self.status = Status.RUNNING
                self.description = after_desc or original
        self._emit_change()

    def suspend(self) -> None:
        """零分保护：进入暂停并阻塞，直到用户恢复或停止。"""
        self._ensure_current()
        with self._cond:
            self._ensure_current()
            if self._stop_event.is_set():
                raise TaskStopped()
            self.status = Status.PAUSED
            self.description = "检测到 0 分，已自动暂停，请检查后恢复"
            self._cond.notify_all()
            while self.status is Status.PAUSED and not self._stop_event.is_set():
                self._ensure_current()
                self._cond.wait(0.5)
            if self._stop_event.is_set():
                raise TaskStopped()
            self.status = Status.RUNNING
        self._emit_change()

    def request_pause(self) -> None:
        with self._cond:
            if self._stop_event.is_set():
                return
            if self.status in (Status.RUNNING, Status.WAITING, Status.NEED_OPERATION):
                self.status = Status.PAUSED
                self.description = "已暂停，等待用户恢复"
                self._cond.notify_all()
        self._emit_change()

    def request_resume(self) -> None:
        with self._cond:
            if self._stop_event.is_set() or self.status is Status.ERROR:
                return
            if self.status is Status.PAUSED:
                if self._awaiting_user and self.user_operation is not None:
                    self.status = Status.NEED_OPERATION
                else:
                    self.status = Status.RUNNING
                self._cond.notify_all()
        self._emit_change()

    def request_stop(self) -> None:
        with self._cond:
            self._stop_event.set()
            self._generation += 1
            self.status = Status.READY
            self.description = "已停止，未启动"
            self._awaiting_user = False
            self._user_op_done = False
            self._cond.notify_all()
        self._emit_change()

    def mark_removed(self) -> None:
        with self._cond:
            self._removed = True
            self._stop_event.set()
            self._generation += 1
            self._cond.notify_all()

    # ------------------------------------------------------------ 状态写入

    def _current_generation(self) -> int | None:
        return getattr(self._tls, "generation", None)

    def set_description(self, text: str) -> None:
        self._update(gen=self._current_generation(), description=text)

    def set_progress(self, completed: int, total: int) -> None:
        self._update(
            gen=self._current_generation(), completed=completed, total=total
        )

    def set_status(self, status: Status) -> None:
        self._update(gen=self._current_generation(), status=status)

    def warn(self, message: str) -> None:
        self.warning = message
        self._emit_change()
        try:
            self._on_warning(message)
        except Exception:
            pass

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def _is_stale(self, generation: int) -> bool:
        return generation != self._generation

    def _update(self, *, gen: int | None = None, **fields) -> bool:
        with self._cond:
            if gen is not None and gen != self._generation:
                return False
            if "status" in fields and fields["status"] is not None:
                self.status = fields["status"]
            if "description" in fields and fields["description"] is not None:
                self.description = fields["description"]
            if "completed" in fields and fields["completed"] is not None:
                self.completed = max(0, int(fields["completed"]))
            if "total" in fields and fields["total"] is not None:
                self.total = max(0, int(fields["total"]))
            self._cond.notify_all()
        self._emit_change()
        return True

    def _set_status_if_current(self, generation: int, status: Status) -> bool:
        return self._update(gen=generation, status=status)

    def _fail(self, message: str) -> None:
        with self._cond:
            if self._removed:
                return
            self.status = Status.ERROR
            self.description = message
            self.error = message
            self._cond.notify_all()
        self._emit_change()
        self._emit_error(message)

    # ------------------------------------------------------------ 对外快照

    def snapshot(self) -> dict:
        with self._cond:
            user = self.user
            snapshot = TaskSnapshot(
                id=self.task_id,
                username=self.username,
                name=self.name,
                status=self.status.value,
                description=self.description,
                completed=self.completed,
                total=self.total,
                progress_percent=(
                    min(100, int(self.completed * 100 / self.total))
                    if self.total > 0
                    else 0
                ),
                user_name=user.name if user else "",
                school_name=user.school_name if user else "",
                user_operation=(
                    self.user_operation.value if self.user_operation else None
                ),
                practice_mode=self.practice_mode,
                duration_param=self._duration_param_text(),
                duration_targets=[item.to_dict() for item in self.duration_targets],
                selected_duration_target=(
                    self.selected_duration_targets[0].to_dict()
                    if self.selected_duration_targets
                    else None
                ),
                selected_duration_targets=[
                    item.to_dict() for item in self.selected_duration_targets
                ],
                courses=[course.to_dict() for course in self.course_list],
                warning=self.warning,
                error=self.error,
            )
            return snapshot.to_dict()

    def _duration_param_text(self) -> str:
        param = self.duration_param
        if isinstance(param, tuple):
            return f"{param[0]},{param[1]}"
        if isinstance(param, int) and param > 0:
            return str(param)
        return ""

    def _emit_change(self) -> None:
        try:
            self._on_change(self.snapshot())
        except Exception:
            logger.exception("Task change callback failed")

    def _emit_error(self, message: str) -> None:
        try:
            self._on_error(message)
        except Exception:
            pass
