#!/usr/bin/env python3
"""
原材料智能分拣系统 - 完整演示
基于 RV1126 开发板的一体化分拣解决方案
"""

import sys
import logging
from pathlib import Path
import cv2
import numpy as np
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from sorting_system import SortingSystem, SystemMode
from order_manager import MaterialType, MaterialColor
from detection.yolov8_postprocess import CLASSES

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SortingSystemDemo:
    """分拣系统演示程序"""
    
    def __init__(self, model_path: str, camera_id: str = "/dev/video52"):
        """
        初始化演示程序
        
        Args:
            model_path: RKNN 模型路径
            camera_id: 摄像头设备ID
        """
        self.model_path = model_path
        self.camera_id = camera_id
        
        # 初始化系统
        self.system = SortingSystem(mode=SystemMode.SINGLE_PIECE)
        
        # 控制参数
        self.running = False
        self.show_debug = True
    
    def setup_demo_orders(self):
        """设置演示用订单"""
        logger.info("Setting up demo orders...")
        
        # 创建 3 个测试订单
        test_orders = [
            ('MAT001', '塑料块', '红色'),
            ('MAT002', '纸盒', '白色'),
            ('MAT003', '塑料块', '蓝色'),
        ]
        
        for material_id, mtype, color in test_orders:
            if self.system.create_test_order(material_id, mtype, color):
                logger.info(f"  ✓ Order created: {material_id} - {color}{mtype}")
        
        # 显示订单统计
        stats = self.system.order_manager.get_statistics()
        logger.info(f"Total orders: {stats['total_orders']}")
    
    def run_interactive_demo(self):
        """交互式演示模式"""
        logger.info("\n" + "="*60)
        logger.info("原材料智能分拣系统 - 交互式演示")
        logger.info("="*60)
        
        # 1. 启动系统
        logger.info("\n[1/4] 系统启动...")
        if not self.system.startup():
            logger.error("Failed to start system")
            return False
        
        logger.info("✓ System started successfully")
        
        # 2. 创建演示订单
        logger.info("\n[2/4] 创建演示订单...")
        self.setup_demo_orders()
        
        # 3. 模拟处理流程
        logger.info("\n[3/4] 模拟物料处理...")
        self.simulate_material_processing()
        
        # 4. 显示系统统计
        logger.info("\n[4/4] 系统统计...")
        self.print_system_stats()
        
        # 5. 关闭系统
        logger.info("\n系统关闭...")
        self.system.shutdown()
        
        return True
    
    def simulate_material_processing(self):
        """
        模拟物料处理流程
        """
        logger.info("Simulating material processing...")
        
        # 创建虚拟检测数据
        # 假设 YOLO 检测到了一个瓶子（塑料类物体）
        mock_boxes = np.array([[100, 100, 200, 200]])
        mock_classes = np.array([39])  # 39 = 'bottle' in COCO
        mock_scores = np.array([0.92])
        
        # 创建虚拟图像
        mock_image = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_image[100:200, 100:200] = [200, 100, 50]  # 模拟蓝色物体
        
        # 场景 1: 正常流程 (MAT001 - 红色塑料块)
        logger.info("\n--- Scenario 1: Normal Case (MAT001) ---")
        # 手动设置 NFC 读卡结果为 MAT001
        self.system.nfc_reader.last_read = {'success': True, 'material_id': 'MAT001'}
        result1 = self.system.process_material(
            vision_boxes=mock_boxes,
            vision_classes=mock_classes,
            vision_scores=mock_scores,
            class_names=list(CLASSES),
            image=mock_image
        )
        self.print_processing_result(result1)
        
        # 场景 2: NFC 异常
        logger.info("\n--- Scenario 2: NFC Error ---")
        self.system.nfc_reader.last_read = {'success': False, 'error': 'No tag'}
        result2 = self.system.process_material(
            vision_boxes=mock_boxes,
            vision_classes=mock_classes,
            vision_scores=mock_scores,
            class_names=list(CLASSES),
            image=mock_image
        )
        self.print_processing_result(result2)
        
        # 场景 3: 查无订单
        logger.info("\n--- Scenario 3: Order Not Found ---")
        self.system.nfc_reader.last_read = {'success': True, 'material_id': 'MAT999'}
        result3 = self.system.process_material(
            vision_boxes=mock_boxes,
            vision_classes=mock_classes,
            vision_scores=mock_scores,
            class_names=list(CLASSES),
            image=mock_image
        )
        self.print_processing_result(result3)
        
        # 场景 4: 重复使用（再次处理 MAT001）
        logger.info("\n--- Scenario 4: Duplicate Material (MAT001 again) ---")
        self.system.nfc_reader.last_read = {'success': True, 'material_id': 'MAT001'}
        result4 = self.system.process_material(
            vision_boxes=mock_boxes,
            vision_classes=mock_classes,
            vision_scores=mock_scores,
            class_names=list(CLASSES),
            image=mock_image
        )
        self.print_processing_result(result4)
    
    def print_processing_result(self, result):
        """打印处理结果"""
        logger.info(f"\nProcessing Result:")
        logger.info(f"  Material ID: {result.material_id}")
        logger.info(f"  Action: {result.action}")
        logger.info(f"  Status: {result.order_status}")
        logger.info(f"  Reason: {result.reason}")
        if result.vision_result:
            logger.info(f"  Vision: {result.vision_result.get('label', 'Unknown')}")
    
    def print_system_stats(self):
        """打印系统统计"""
        logger.info("\n=== System Statistics ===")
        
        system_status = self.system.get_system_status()
        orders_stats = system_status['orders']
        decision_stats = system_status['decisions']
        
        logger.info(f"\nOrders:")
        logger.info(f"  Total: {orders_stats['total_orders']}")
        logger.info(f"  Passed: {orders_stats['passed']}")
        logger.info(f"  Anomaly: {orders_stats['anomaly']}")
        logger.info(f"  Waiting Manual: {orders_stats['waiting_manual']}")
        logger.info(f"  Pending: {orders_stats['pending']}")
        
        logger.info(f"\nDecisions:")
        logger.info(f"  Total: {decision_stats['total']}")
        logger.info(f"  Pass: {decision_stats['pass']}")
        logger.info(f"  Sort: {decision_stats['sort']}")
        logger.info(f"  Manual: {decision_stats['manual']}")
        
        logger.info(f"\nDevice:")
        logger.info(f"  Health Status: {system_status['device_health']}")
        logger.info(f"  Ready: {system_status['ready']}")
        
        # 显示所有订单详情
        logger.info(f"\nOrder Details:")
        for material_id in self.system.order_manager.orders:
            order_dict = self.system.order_manager.to_dict(material_id)
            logger.info(f"  {material_id}:")
            logger.info(f"    Status: {order_dict['status']}")
            logger.info(f"    Type: {order_dict['material_type']} {order_dict['color']}")
            logger.info(f"    Notes: {order_dict['notes']}")
    
    def print_system_info(self):
        """打印系统信息"""
        logger.info("\n" + "="*60)
        logger.info("原材料智能分拣与设备监测系统")
        logger.info("="*60)
        logger.info(f"System Version: {self.system.__class__.__module__}")
        logger.info(f"Mode: {self.system.mode.value}")
        logger.info(f"Confidence Threshold: {self.system.confidence_threshold:.1%}")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")
        logger.info("="*60)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="原材料智能分拣系统演示"
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='./rknnModel/best.rknn',
        help='RKNN model path'
    )
    
    parser.add_argument(
        '--camera',
        type=str,
        default='/dev/video52',
        help='Camera device ID'
    )
    
    parser.add_argument(
        '--info',
        action='store_true',
        help='Show system info only'
    )
    
    args = parser.parse_args()
    
    # 创建演示程序
    demo = SortingSystemDemo(model_path=args.model, camera_id=args.camera)
    
    # 显示系统信息
    demo.print_system_info()
    
    if args.info:
        return 0
    
    # 运行交互式演示
    try:
        success = demo.run_interactive_demo()
        return 0 if success else 1
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
