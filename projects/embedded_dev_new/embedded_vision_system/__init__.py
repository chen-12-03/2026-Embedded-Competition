"""
Embedded Vision System
For RV1126 embedded board - Intelligent Material Sorting System
"""

__version__ = "0.2.0"

# 摄像头/视觉模块在没有 OpenCV 或 RKNN 依赖时允许降级导入，
# 这样订单管理、Web API、业务规则测试仍然可用。
try:
    from .camera import (
        CameraManager,
        FrameBuffer,
        FrameRateTracker,
        LatestFrameReader,
        LatestJPEGProcessor,
        CameraWebPreviewService,
    )
except Exception:  # pragma: no cover - 依赖缺失时降级
    CameraManager = None
    FrameBuffer = None
    FrameRateTracker = None
    LatestFrameReader = None
    LatestJPEGProcessor = None
    CameraWebPreviewService = None

try:
    from .detection.rknn_engine import RKNNInference, RKNNPoolExecutor
except Exception:  # pragma: no cover - RKNN 依赖缺失时降级
    RKNNInference = None
    RKNNPoolExecutor = None

try:
    from .detection.vision_classifier import (
        MaterialClassifier,
        VisionResultConverter,
        NFC_Reader_Mock,
    )
except Exception:  # pragma: no cover - OpenCV 依赖缺失时降级
    MaterialClassifier = None
    VisionResultConverter = None
    NFC_Reader_Mock = None

try:
    from .detection.shape_color_classifier import (
        ShapeColorClassificationResult,
        ShapeColorResultConverter,
        TraditionalShapeColorClassifier,
    )
except Exception:  # pragma: no cover - OpenCV 依赖缺失时降级
    ShapeColorClassificationResult = None
    ShapeColorResultConverter = None
    TraditionalShapeColorClassifier = None

try:
    from .utils.vision_pipeline import VisionPipeline
except Exception:  # pragma: no cover - 视觉依赖缺失时降级
    VisionPipeline = None

# 共享硬件模块
from .hardware import (
    BaseNFCReader,
    MockNFCReader,
    FileNFCReader,
    CommandNFCReader,
    PN532PinConfig,
    PN532I2CTransport,
    PN532SPITransport,
    PN532UARTTransport,
    PN532NFCReader,
    extract_material_id_from_payload,
    create_nfc_reader,
    BasePWMBackend,
    MockPWMBackend,
    SysfsPWMBackend,
    ServoPWMController,
    ConveyorPWMController,
    create_pwm_backend,
    BaseGPIOOutput,
    MockGPIOOutput,
    SysfsGPIOOutput,
    create_gpio_output,
    SoftwarePWMGPIOBackend,
    STM32ControlStatus,
    STM32SerialController,
    STM32ServoController,
    STM32StepperConveyorController,
    SensorReading,
    MockVibrationSensor,
    MockCurrentSensor,
    MPU6050,
    MPU6050Reading,
    MPU6050VibrationSensor,
    MPU6050_DEFAULT_ADDRESS,
    MPU6050_ALT_ADDRESS,
)

# 订单管理
from .order_manager import (
    OrderManager,
    Order,
    OrderStatus,
    MaterialType,
    MaterialColor,
    MaterialSpec,
    HistoryRecord,
    normalize_color,
    normalize_material_type,
    normalize_shape,
)

# 设备控制
from .device_controller import (
    DeviceController,
    ServoController,
    ConveyorBelt,
    HealthLevel,
    build_device_controller,
)

# 一致性比对
from .consistency_engine import ConsistencyEngine, EnhancedSortingDecisionEngine, ComparisonStatus

try:
    from .sorting_system import SortingSystem, SystemMode
except Exception:  # pragma: no cover - 视觉依赖缺失时降级
    SortingSystem = None
    SystemMode = None

try:
    from .board_runtime import BoardRuntimeConfig, BoardSortingRuntime
except Exception:  # pragma: no cover - 摄像头/存储依赖缺失时降级
    BoardRuntimeConfig = None
    BoardSortingRuntime = None

__all__ = [
    # 基础
    'CameraManager',
    'FrameBuffer',
    'FrameRateTracker',
    'LatestFrameReader',
    'LatestJPEGProcessor',
    'CameraWebPreviewService',
    'RKNNInference',
    'RKNNPoolExecutor',
    'VisionPipeline',

    # 共享硬件
    'BaseNFCReader',
    'MockNFCReader',
    'FileNFCReader',
    'CommandNFCReader',
    'PN532PinConfig',
    'PN532I2CTransport',
    'PN532SPITransport',
    'PN532UARTTransport',
    'PN532NFCReader',
    'extract_material_id_from_payload',
    'create_nfc_reader',
    'BasePWMBackend',
    'MockPWMBackend',
    'SysfsPWMBackend',
    'ServoPWMController',
    'ConveyorPWMController',
    'create_pwm_backend',
    'BaseGPIOOutput',
    'MockGPIOOutput',
    'SysfsGPIOOutput',
    'create_gpio_output',
    'SoftwarePWMGPIOBackend',
    'STM32ControlStatus',
    'STM32SerialController',
    'STM32ServoController',
    'STM32StepperConveyorController',
    'SensorReading',
    'MockVibrationSensor',
    'MockCurrentSensor',
    'MPU6050',
    'MPU6050Reading',
    'MPU6050VibrationSensor',
    'MPU6050_DEFAULT_ADDRESS',
    'MPU6050_ALT_ADDRESS',
    
    # 视觉分类
    'MaterialClassifier',
    'VisionResultConverter',
    'NFC_Reader_Mock',
    'ShapeColorClassificationResult',
    'ShapeColorResultConverter',
    'TraditionalShapeColorClassifier',
    
    # 订单管理
    'OrderManager',
    'Order',
    'OrderStatus',
    'MaterialType',
    'MaterialColor',
    'MaterialSpec',
    'HistoryRecord',
    'normalize_color',
    'normalize_material_type',
    'normalize_shape',
    
    # 设备控制
    'DeviceController',
    'ServoController',
    'ConveyorBelt',
    'HealthLevel',
    'build_device_controller',
    
    # 一致性比对
    'ConsistencyEngine',
    'EnhancedSortingDecisionEngine',
    'ComparisonStatus',
    
    # 完整系统
    'SortingSystem',
    'SystemMode',
    'BoardRuntimeConfig',
    'BoardSortingRuntime',
]
