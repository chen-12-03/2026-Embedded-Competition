"""
RKNN 推理引擎模块
支持单模型和线程池并行推理
"""

import logging
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from rknnlite.api import RKNNLite
except ImportError:
    logging.warning("rknnlite not installed. RKNN inference will not work.")
    RKNNLite = None

logger = logging.getLogger(__name__)


class RKNNInference:
    """
    单个 RKNN 推理引擎
    """
    
    def __init__(self, model_path: str, device_id: int = 0):
        """
        初始化 RKNN 推理引擎
        
        Args:
            model_path: RKNN 模型文件路径
            device_id: 设备 ID（用于多设备场景）
        """
        if RKNNLite is None:
            raise RuntimeError(
                "rknnlite not installed. "
                "Please install: pip install rknnlite"
            )
        
        self.model_path = model_path
        self.device_id = device_id
        self.rknn = RKNNLite()
        
        # 加载模型
        ret = self.rknn.load_rknn(model_path)
        if ret != 0:
            raise RuntimeError(f"Failed to load RKNN model: {model_path}")
        
        # 初始化运行时环境
        ret = self.rknn.init_runtime()
        if ret != 0:
            raise RuntimeError("Failed to initialize RKNN runtime environment")
        
        logger.info(f"RKNN model loaded successfully: {model_path}")
    
    def inference(self, image_data):
        """
        执行推理
        
        Args:
            image_data: 输入图像数据 [1, H, W, C]
        
        Returns:
            推理输出列表
        """
        outputs = self.rknn.inference(inputs=[image_data], data_format=['nhwc'])
        return outputs
    
    def release(self):
        """释放 RKNN 资源"""
        if self.rknn is not None:
            self.rknn.release()


class RKNNPoolExecutor:
    """
    RKNN 推理线程池
    支持异步推理以提高帧率
    """
    
    def __init__(self, model_path: str, num_threads: int = 4):
        """
        初始化推理线程池
        
        Args:
            model_path: RKNN 模型文件路径
            num_threads: 线程数（推理并行度）
        """
        self.model_path = model_path
        self.num_threads = num_threads
        self.queue = Queue()
        self.thread_pool = ThreadPoolExecutor(max_workers=num_threads)
        self.rknn_models = []
        self.frame_count = 0
        
        # 初始化多个 RKNN 模型实例
        for i in range(num_threads):
            try:
                rknn = RKNNInference(model_path, device_id=i)
                self.rknn_models.append(rknn)
            except Exception as e:
                logger.error(f"Failed to initialize RKNN model {i}: {e}")
                self.release()
                raise
        
        logger.info(f"RKNN pool initialized with {num_threads} threads")
    
    def submit_task(self, image_data, inference_func):
        """
        提交推理任务
        
        Args:
            image_data: 输入图像数据
            inference_func: 推理函数，接收 (rknn_model, image_data) 
                           并返回处理后的结果
        
        Returns:
            None
        """
        model_idx = self.frame_count % self.num_threads
        rknn_model = self.rknn_models[model_idx]
        
        future = self.thread_pool.submit(inference_func, rknn_model, image_data)
        self.queue.put(future)
        self.frame_count += 1
    
    def get_result(self, timeout: float = 5.0):
        """
        获取推理结果
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            (result, success) - result 为推理结果，success 为是否成功
        """
        if self.queue.empty():
            return None, False
        
        try:
            future = self.queue.get()
            result = future.result(timeout=timeout)
            return result, True
        except Exception as e:
            logger.error(f"Error getting result: {e}")
            return None, False
    
    def release(self):
        """释放所有资源"""
        self.thread_pool.shutdown(wait=True)
        for rknn in self.rknn_models:
            try:
                rknn.release()
            except Exception as e:
                logger.error(f"Error releasing RKNN: {e}")
        logger.info("RKNN pool released")
    
    def get_frame_count(self) -> int:
        """获取已处理的帧数"""
        return self.frame_count


# 快速推理函数示例
def simple_inference(rknn_model, image_data):
    """
    简单推理包装函数
    
    Args:
        rknn_model: RKNNInference 实例
        image_data: 输入图像数据
    
    Returns:
        推理输出
    """
    return rknn_model.inference(image_data)
