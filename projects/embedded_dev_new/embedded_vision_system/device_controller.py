"""
设备控制模块
管理传送带、舵机、传感器、自检和健康监测

说明：
- 这里的执行器和传感器已经重构到共享硬件模块
- `basic_function_tests` 和完整系统会共同复用同一套底层实现
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional
import time

from .board_defaults import (
    DEFAULT_BOARD_CONVEYOR_HALF_TRAVEL_SECONDS,
    DEFAULT_BOARD_CONVEYOR_SPEED,
    DEFAULT_BOARD_CONVEYOR_SPEED_MODE,
    DEFAULT_BOARD_CONVEYOR_STEP_MAX_HZ,
    DEFAULT_BOARD_CONTROL_UART_BAUDRATE,
    DEFAULT_BOARD_CONTROL_UART_PORT,
    DEFAULT_BOARD_CONTROL_UART_TIMEOUT,
    DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
    DEFAULT_BOARD_MPU6050_I2C_BUS,
    DEFAULT_BOARD_MPU6050_RED_THRESHOLD,
    DEFAULT_BOARD_MPU6050_YELLOW_THRESHOLD,
    DEFAULT_BOARD_SERVO_NORMAL_ANGLE,
    DEFAULT_BOARD_SERVO_SORT_ANGLE,
    DEFAULT_BOARD_SERVO_SORT_SECONDARY_ANGLE,
    DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS,
    DEFAULT_BOARD_SORT_PREPARE_PAUSE_SECONDS,
    DEFAULT_BOARD_SORT_SERVO_OSCILLATION_INTERVAL,
    DEFAULT_BOARD_SORT_SERVO_SETTLE_SECONDS,
    DEFAULT_BOARD_VIBRATION_BACKEND,
)
from .hardware import (
    ConveyorPWMController,
    MockCurrentSensor,
    MockVibrationSensor,
    MPU6050VibrationSensor,
    ServoPWMController,
    SoftwarePWMGPIOBackend,
    STM32SerialController,
    STM32ServoController,
    STM32StepperConveyorController,
    create_gpio_output,
    create_pwm_backend,
)

logger = logging.getLogger(__name__)


class ServoAngle(Enum):
    """舵机角度预设"""

    NORMAL = DEFAULT_BOARD_SERVO_NORMAL_ANGLE
    SORT = DEFAULT_BOARD_SERVO_SORT_ANGLE


class ConveyorState(Enum):
    """传送带状态"""

    STOPPED = "停止"
    RUNNING = "运行"
    ERROR = "异常"


class HealthLevel(Enum):
    """设备健康分级"""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class ComponentCheck:
    """自检结果"""

    ok: bool
    message: str

    def to_dict(self) -> Dict:
        return {"ok": self.ok, "message": self.message}


class ServoController(ServoPWMController):
    """设备层舵机控制器，复用共享 PWM 实现。"""


class ConveyorBelt(ConveyorPWMController):
    """设备层传送带控制器，复用共享 PWM 实现。"""

    @property
    def state(self) -> ConveyorState:
        return ConveyorState.RUNNING if self.current_speed > 0 else ConveyorState.STOPPED

    def get_status(self) -> Dict:
        return {
            "state": self.state.value,
            "speed": self.current_speed,
            "enabled": self.enabled,
        }


class VibrationSensor(MockVibrationSensor):
    """设备层振动传感器，复用共享模拟传感器实现。"""

    def classify(self, value: float) -> HealthLevel:
        if value >= self.red_threshold:
            return HealthLevel.RED
        if value >= self.yellow_threshold:
            return HealthLevel.YELLOW
        return HealthLevel.GREEN


class CurrentSensor(MockCurrentSensor):
    """设备层电流传感器，复用共享模拟传感器实现。"""

    def classify(self, value: float) -> HealthLevel:
        low, high = self.normal_range
        if value < low - self.red_margin or value > high + self.red_margin:
            return HealthLevel.RED
        if value < low - self.yellow_margin or value > high + self.yellow_margin:
            return HealthLevel.YELLOW
        return HealthLevel.GREEN


def build_device_controller(
    *,
    servo_backend: str = "mock",
    servo_chip: int = 0,
    servo_channel: int = 0,
    servo_gpio: Optional[int] = None,
    servo_normal_angle: int = DEFAULT_BOARD_SERVO_NORMAL_ANGLE,
    servo_sort_angle: int = DEFAULT_BOARD_SERVO_SORT_ANGLE,
    servo_sort_secondary_angle: Optional[int] = DEFAULT_BOARD_SERVO_SORT_SECONDARY_ANGLE,
    conveyor_backend: str = "mock",
    conveyor_chip: int = 0,
    conveyor_channel: int = 1,
    conveyor_pwm_gpio: Optional[int] = None,
    conveyor_enable_gpio: Optional[int] = None,
    gpio_backend: str = "sysfs",
    default_conveyor_speed: int = DEFAULT_BOARD_CONVEYOR_SPEED,
    vibration_backend: str = DEFAULT_BOARD_VIBRATION_BACKEND,
    vibration_i2c_bus: int = DEFAULT_BOARD_MPU6050_I2C_BUS,
    vibration_i2c_address: int = DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
    vibration_yellow_threshold: float = DEFAULT_BOARD_MPU6050_YELLOW_THRESHOLD,
    vibration_red_threshold: float = DEFAULT_BOARD_MPU6050_RED_THRESHOLD,
    control_uart_port: str = DEFAULT_BOARD_CONTROL_UART_PORT,
    control_uart_baudrate: int = DEFAULT_BOARD_CONTROL_UART_BAUDRATE,
    control_uart_timeout: float = DEFAULT_BOARD_CONTROL_UART_TIMEOUT,
    conveyor_speed_mode: str = DEFAULT_BOARD_CONVEYOR_SPEED_MODE,
    conveyor_step_max_hz: int = DEFAULT_BOARD_CONVEYOR_STEP_MAX_HZ,
    sort_prepare_pause: float = DEFAULT_BOARD_SORT_PREPARE_PAUSE_SECONDS,
    sort_servo_settle_time: float = DEFAULT_BOARD_SORT_SERVO_SETTLE_SECONDS,
    sort_servo_oscillation_interval: float = DEFAULT_BOARD_SORT_SERVO_OSCILLATION_INTERVAL,
    sort_conveyor_advance_time: float = DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS,
    current_fault_enabled: bool = False,
    serial_factory: Optional[Callable[..., Any]] = None,
) -> "DeviceController":
    """按后端配置创建统一设备控制器。"""
    if vibration_backend == "mpu6050":
        vibration = MPU6050VibrationSensor(
            bus_id=vibration_i2c_bus,
            address=vibration_i2c_address,
            yellow_threshold=vibration_yellow_threshold,
            red_threshold=vibration_red_threshold,
        )
    elif vibration_backend == "mock":
        vibration = VibrationSensor(
            yellow_threshold=vibration_yellow_threshold,
            red_threshold=vibration_red_threshold,
        )
    else:
        raise ValueError(f"unsupported vibration backend: {vibration_backend}")

    uses_stm32_uart = (
        servo_backend == "stm32_uart" or conveyor_backend == "stm32_uart"
    )
    if uses_stm32_uart:
        if servo_backend != "stm32_uart" or conveyor_backend != "stm32_uart":
            raise ValueError(
                "servo_backend and conveyor_backend must both be `stm32_uart`"
            )

        client = STM32SerialController(
            port=control_uart_port,
            baudrate=control_uart_baudrate,
            timeout=control_uart_timeout,
            serial_factory=serial_factory,
            # Let the WebUI boot even if STM32 is still starting up; the
            # first explicit health check/start action will query STATUS.
            auto_query_status=False,
        )
        servo = STM32ServoController(
            client=client,
            normal_angle=servo_normal_angle,
            sort_angle=servo_sort_angle,
        )
        conveyor = STM32StepperConveyorController(
            client=client,
            speed_mode=conveyor_speed_mode,
            max_step_hz=conveyor_step_max_hz,
        )
        return DeviceController(
            servo=servo,
            conveyor=conveyor,
            vibration=vibration,
            default_conveyor_speed=default_conveyor_speed,
            sort_prepare_pause=sort_prepare_pause,
            sort_servo_settle_time=sort_servo_settle_time,
            sort_servo_secondary_angle=servo_sort_secondary_angle,
            sort_servo_oscillation_interval=sort_servo_oscillation_interval,
            sort_conveyor_advance_time=sort_conveyor_advance_time,
            current_fault_enabled=current_fault_enabled,
        )

    if servo_backend == "gpio":
        servo_pwm_backend = SoftwarePWMGPIOBackend(
            signal_gpio=create_gpio_output(gpio_backend, servo_gpio),
        )
    else:
        servo_pwm_backend = create_pwm_backend(
            servo_backend,
            chip=servo_chip,
            channel=servo_channel,
        )

    if conveyor_backend == "gpio":
        conveyor_pwm_backend = SoftwarePWMGPIOBackend(
            signal_gpio=create_gpio_output(gpio_backend, conveyor_pwm_gpio),
            enable_gpio=create_gpio_output(gpio_backend, conveyor_enable_gpio),
        )
    else:
        conveyor_pwm_backend = create_pwm_backend(
            conveyor_backend,
            chip=conveyor_chip,
            channel=conveyor_channel,
        )

    servo = ServoController(
        backend=servo_pwm_backend,
        normal_angle=servo_normal_angle,
        sort_angle=servo_sort_angle,
    )
    conveyor = ConveyorBelt(backend=conveyor_pwm_backend)
    return DeviceController(
        servo=servo,
        conveyor=conveyor,
        vibration=vibration,
        default_conveyor_speed=default_conveyor_speed,
        sort_prepare_pause=sort_prepare_pause,
        sort_servo_settle_time=sort_servo_settle_time,
        sort_servo_secondary_angle=servo_sort_secondary_angle,
        sort_servo_oscillation_interval=sort_servo_oscillation_interval,
        sort_conveyor_advance_time=sort_conveyor_advance_time,
        current_fault_enabled=current_fault_enabled,
    )


class DeviceController:
    """设备综合控制器"""

    def __init__(
        self,
        servo: Optional[Any] = None,
        conveyor: Optional[Any] = None,
        vibration: Optional[VibrationSensor] = None,
        current: Optional[CurrentSensor] = None,
        default_conveyor_speed: int = 50,
        sort_prepare_pause: float = DEFAULT_BOARD_SORT_PREPARE_PAUSE_SECONDS,
        sort_servo_settle_time: float = DEFAULT_BOARD_SORT_SERVO_SETTLE_SECONDS,
        sort_servo_secondary_angle: Optional[int] = DEFAULT_BOARD_SERVO_SORT_SECONDARY_ANGLE,
        sort_servo_oscillation_interval: float = DEFAULT_BOARD_SORT_SERVO_OSCILLATION_INTERVAL,
        sort_conveyor_advance_time: float = DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS,
        current_fault_enabled: bool = False,
    ):
        self.servo = servo or ServoController()
        self.conveyor = conveyor or ConveyorBelt()
        self.vibration = vibration or VibrationSensor()
        self.current = current or CurrentSensor()
        self.default_conveyor_speed = int(default_conveyor_speed)
        self.last_running_speed = self.default_conveyor_speed
        self.sort_prepare_pause = max(0.0, float(sort_prepare_pause))
        self.sort_servo_settle_time = max(0.0, float(sort_servo_settle_time))
        self.sort_servo_secondary_angle = (
            None if sort_servo_secondary_angle is None else int(sort_servo_secondary_angle)
        )
        self.sort_servo_oscillation_interval = max(0.0, float(sort_servo_oscillation_interval))
        self.sort_conveyor_advance_time = max(0.0, float(sort_conveyor_advance_time))
        self.current_fault_enabled = bool(current_fault_enabled)

        self.is_running = False
        self.health_status = HealthLevel.GREEN.value
        self.alert_latched = False
        self.last_health_snapshot: Optional[Dict] = None
        self.last_startup_check: Optional[Dict] = None

        self.component_checks: Dict[str, Callable[[], ComponentCheck]] = {
            "camera": self._check_camera,
            "nfc": self._check_nfc,
            "conveyor": self._check_conveyor,
            "servo": self._check_servo,
            "network": self._check_network,
            "sensors": self._check_sensors,
        }
        logger.info("Device controller initialized")

    def set_component_check(self, name: str, callback: Callable[[], ComponentCheck]) -> None:
        """注册真实硬件自检回调。"""
        self.component_checks[name] = callback

    def inject_sensor_values(
        self,
        vibration: Optional[float] = None,
        current: Optional[float] = None,
    ) -> None:
        """为联调或测试手动注入传感器读数。"""
        if vibration is not None:
            self.vibration.inject(vibration)
        if current is not None:
            self.current.inject(current)

    def startup_check(self) -> Dict:
        """启动前自检。"""
        logger.info("Starting device health check...")
        results = {}
        for name, callback in self.component_checks.items():
            try:
                result = callback()
            except Exception as exc:
                logger.exception("Component check failed: %s", name)
                result = ComponentCheck(
                    ok=False,
                    message=f"{type(exc).__name__}: {exc}",
                )
            results[name] = result.to_dict()
        self.last_startup_check = results

        all_pass = all(item["ok"] for item in results.values())
        self.health_status = HealthLevel.GREEN.value if all_pass else HealthLevel.YELLOW.value
        return results

    def _check_camera(self) -> ComponentCheck:
        return ComponentCheck(ok=True, message="摄像头在线")

    def _check_nfc(self) -> ComponentCheck:
        return ComponentCheck(ok=True, message="NFC 模块在线")

    def _check_conveyor(self) -> ComponentCheck:
        refresh_status = getattr(self.conveyor, "refresh_status", None)
        if callable(refresh_status):
            refresh_status()
        status = self.conveyor.get_status()
        return ComponentCheck(ok=True, message=f"传送带就绪: {status}")

    def _check_servo(self) -> ComponentCheck:
        refresh_status = getattr(self.servo, "refresh_status", None)
        if callable(refresh_status):
            refresh_status()
        return ComponentCheck(ok=True, message=f"舵机角度: {self.servo.get_current_angle()}°")

    def _check_network(self) -> ComponentCheck:
        return ComponentCheck(ok=True, message="网络/服务连通")

    def _check_sensors(self) -> ComponentCheck:
        vib = self.vibration.read()
        cur = self.current.read()
        return ComponentCheck(
            ok=True,
            message=f"传感器在线: Vib={vib.value:.2f}, Cur={cur.value:.2f}A",
        )

    def start(self, speed: Optional[int] = None, skip_check: bool = False) -> bool:
        """启动设备。"""
        if self.alert_latched:
            logger.warning("Device is latched in alarm state, reset required before start")
            return False

        target_speed = self.default_conveyor_speed if speed is None else int(speed)

        if not skip_check:
            checks = self.startup_check()
            if not all(item["ok"] for item in checks.values()):
                logger.error("Startup check failed, cannot start")
                return False

        if not self.servo.normal_position():
            logger.error("Failed to move servo to normal position")
            self.health_status = HealthLevel.RED.value
            return False

        if not self.conveyor.start(speed=target_speed):
            self.health_status = HealthLevel.RED.value
            return False

        self.last_running_speed = target_speed
        self.is_running = True
        return True

    def stop(self) -> bool:
        """停止设备。"""
        self.conveyor.stop()
        self.servo.normal_position()
        self.is_running = False
        return True

    def pause_conveyor(self) -> bool:
        """暂停传送带，保留设备运行态。"""
        if not self.is_running:
            logger.warning("Device not running")
            return False

        if self.conveyor.current_speed > 0:
            self.last_running_speed = self.conveyor.current_speed
        self.conveyor.stop()
        return True

    def resume_conveyor(self, speed: Optional[int] = None) -> bool:
        """恢复传送带运行。"""
        if self.alert_latched:
            logger.warning("Device is latched in alarm state, cannot resume conveyor")
            return False
        if not self.is_running:
            logger.warning("Device not running")
            return False

        target_speed = (
            int(speed)
            if speed is not None
            else (self.last_running_speed if self.last_running_speed > 0 else self.default_conveyor_speed)
        )
        if not self.conveyor.start(speed=target_speed):
            logger.error("Failed to resume conveyor at speed %s", target_speed)
            return False
        self.last_running_speed = target_speed
        return True

    def emergency_stop(self, reason: str) -> bool:
        """严重异常停机。"""
        logger.error("Emergency stop triggered: %s", reason)
        self.alert_latched = True
        self.health_status = HealthLevel.RED.value
        return self.stop()

    def reset_faults(self) -> None:
        """人工复位告警。"""
        self.alert_latched = False
        self.health_status = HealthLevel.GREEN.value

    def get_sort_timing(self) -> Dict[str, float]:
        """返回当前分拣动作时序参数，便于板机联调时直接核对。"""
        return {
            "prepare_pause": self.sort_prepare_pause,
            "servo_settle_time": self.sort_servo_settle_time,
            "conveyor_advance_time": self.sort_conveyor_advance_time,
            "conveyor_half_travel_seconds": DEFAULT_BOARD_CONVEYOR_HALF_TRAVEL_SECONDS,
        }

    def _set_servo_angle(self, angle: int) -> bool:
        set_angle = getattr(self.servo, "set_angle", None)
        if callable(set_angle):
            return bool(set_angle(int(angle)))
        logger.error("Servo controller does not expose set_angle, cannot move to %s°", angle)
        return False

    def _hold_or_oscillate_sort_servo(self, duration: float) -> bool:
        if duration <= 0:
            return True

        primary_angle = int(getattr(self.servo, "sort_angle", self.servo.get_current_angle()))
        secondary_angle = self.sort_servo_secondary_angle
        interval = self.sort_servo_oscillation_interval

        if secondary_angle is None or int(secondary_angle) == primary_angle or interval <= 0:
            time.sleep(duration)
            return True

        deadline = time.monotonic() + float(duration)
        next_toggle = time.monotonic() + float(interval)
        next_angle = int(secondary_angle)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            sleep_for = min(max(0.0, next_toggle - time.monotonic()), remaining)
            if sleep_for > 0:
                time.sleep(sleep_for)

            if time.monotonic() >= deadline:
                break

            if not self._set_servo_angle(next_angle):
                logger.error("Failed to oscillate servo to %s°", next_angle)
                return False
            next_angle = primary_angle if next_angle == int(secondary_angle) else int(secondary_angle)
            next_toggle += float(interval)
        return True

    def execute_sort(
        self,
        hold_time: Optional[float] = None,
        *,
        prepare_pause: Optional[float] = None,
        servo_settle_time: Optional[float] = None,
        conveyor_advance_time: Optional[float] = None,
    ) -> bool:
        """
        执行分拣动作。

        `hold_time` 为兼容旧调用保留，等价于 `conveyor_advance_time`：
        也就是舵机保持在异常拨料角度、同时让物料继续前行通过拨料位的时间。
        """
        if not self.is_running:
            logger.warning("Device not running")
            return False

        effective_prepare_pause = (
            self.sort_prepare_pause
            if prepare_pause is None
            else max(0.0, float(prepare_pause))
        )
        effective_servo_settle_time = (
            self.sort_servo_settle_time
            if servo_settle_time is None
            else max(0.0, float(servo_settle_time))
        )
        if conveyor_advance_time is None and hold_time is not None:
            conveyor_advance_time = hold_time
        effective_conveyor_advance_time = (
            self.sort_conveyor_advance_time
            if conveyor_advance_time is None
            else max(0.0, float(conveyor_advance_time))
        )

        resume_speed = self.conveyor.current_speed or self.last_running_speed or self.default_conveyor_speed
        conveyor_was_running = self.conveyor.current_speed > 0
        if conveyor_was_running and not self.pause_conveyor():
            return False
        if effective_prepare_pause > 0:
            time.sleep(effective_prepare_pause)
        if not self.servo.sort_position():
            logger.error("Failed to move servo to sort position")
            return False
        if effective_servo_settle_time > 0:
            time.sleep(effective_servo_settle_time)
        if not self.resume_conveyor(speed=resume_speed):
            logger.error("Failed to resume conveyor while servo is in sort position")
            self.servo.normal_position()
            return False
        if not self._hold_or_oscillate_sort_servo(effective_conveyor_advance_time):
            self.servo.normal_position()
            return False
        if not self.servo.normal_position():
            logger.error("Failed to move servo back to normal position")
            return False
        return True

    def monitor_health(self) -> Dict:
        """监测健康状态，并在黄色/红色告警时触发停机保护。"""
        return self._collect_health_snapshot(trigger_stop=True)

    def read_health_snapshot(self) -> Dict:
        """被动读取健康快照，不执行红色故障停机副作用。"""
        return self._collect_health_snapshot(trigger_stop=False)

    def _collect_health_snapshot(self, *, trigger_stop: bool) -> Dict:
        vib_reading = self.vibration.read()
        cur_reading = self.current.read()

        vibration_level = self.vibration.classify(vib_reading.value)
        current_level = self.current.classify(cur_reading.value)
        if self.current_fault_enabled:
            overall_level = self._merge_levels(vibration_level, current_level)
        else:
            overall_level = vibration_level

        reasons = []
        if vibration_level == HealthLevel.YELLOW:
            reasons.append("设备黄色告警")
        elif vibration_level == HealthLevel.RED:
            reasons.append("设备红色故障")

        current_level_text = current_level.value if self.current_fault_enabled else "monitor_only"

        snapshot = {
            "overall": overall_level.value,
            "sampled_at": max(vib_reading.timestamp, cur_reading.timestamp),
            "vibration": {
                "value": vib_reading.value,
                "level": vibration_level.value,
                "average": self.vibration.get_average(),
                "sampled_at": vib_reading.timestamp,
            },
            "current": {
                "value": cur_reading.value,
                "level": current_level_text,
                "average": self.current.get_average(),
                "sampled_at": cur_reading.timestamp,
                "fault_enabled": self.current_fault_enabled,
            },
            "alert_latched": self.alert_latched,
            "reasons": reasons,
        }

        self.last_health_snapshot = snapshot
        self.health_status = overall_level.value

        if trigger_stop and overall_level in (HealthLevel.YELLOW, HealthLevel.RED):
            stop_reason = (
                "设备健康状态达到红色故障"
                if overall_level == HealthLevel.RED
                else "设备健康状态达到黄色告警"
            )
            if overall_level == HealthLevel.RED:
                logger.error("Protective stop triggered: %s", stop_reason)
            else:
                logger.warning("Protective stop triggered: %s", stop_reason)
            self.alert_latched = True
            self.stop()
            self.health_status = overall_level.value
            snapshot["alert_latched"] = True
            snapshot["stopped"] = True
        else:
            snapshot["stopped"] = False

        return snapshot

    def _merge_levels(self, *levels: HealthLevel) -> HealthLevel:
        if any(level == HealthLevel.RED for level in levels):
            return HealthLevel.RED
        if any(level == HealthLevel.YELLOW for level in levels):
            return HealthLevel.YELLOW
        return HealthLevel.GREEN

    def get_device_status(self) -> Dict:
        """获取设备状态。"""
        return {
            "running": self.is_running,
            "health": self.health_status,
            "alert_latched": self.alert_latched,
            "conveyor": self.conveyor.get_status(),
            "vibration_backend": type(self.vibration).__name__,
            "servo_angle": self.servo.get_current_angle(),
            "servo_normal_angle": getattr(self.servo, "normal_angle", None),
            "servo_sort_angle": getattr(self.servo, "sort_angle", None),
            "servo_sort_secondary_angle": self.sort_servo_secondary_angle,
            "sort_servo_oscillation_interval": self.sort_servo_oscillation_interval,
            "sort_timing": self.get_sort_timing(),
            "last_health_snapshot": self.last_health_snapshot,
            "last_startup_check": self.last_startup_check,
        }

    def close(self) -> None:
        """释放底层硬件资源。"""
        for component in (self.conveyor, self.servo, self.vibration, self.current):
            cleanup = getattr(component, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    logger.exception("Failed to cleanup component: %s", type(component).__name__)
            close = getattr(component, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.exception("Failed to close component: %s", type(component).__name__)
