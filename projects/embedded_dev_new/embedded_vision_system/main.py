#!/usr/bin/env python3
"""
嵌入式视觉系统 - 主程序示例
支持 RV1126 开发板的独立摄像头检测系统
"""

import sys
import time
import logging
import argparse
import cv2
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入视觉系统模块
sys.path.insert(0, str(Path(__file__).parent))
from embedded_vision_system.storage import describe_storage_root, ensure_managed_path
from embedded_vision_system.utils.vision_pipeline import VisionPipeline


def main():
    """主程序"""
    parser = argparse.ArgumentParser(
        description="嵌入式摄像头目标检测系统"
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='./rknnModel/best.rknn',
        help='RKNN 模型文件路径 (default: ./rknnModel/best.rknn)'
    )
    
    parser.add_argument(
        '--camera',
        type=str,
        default='/dev/video52',
        help='摄像头设备路径或索引 (default: /dev/video52)'
    )
    
    parser.add_argument(
        '--threads',
        type=int,
        default=8,
        help='推理线程数 (default: 8)'
    )
    
    parser.add_argument(
        '--sync',
        action='store_true',
        help='使用同步推理（禁用异步）'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='输出视频文件路径 (可选)'
    )
    
    args = parser.parse_args()
    
    # 检查模型文件
    if not Path(args.model).exists():
        logger.error(f"RKNN model not found: {args.model}")
        sys.exit(1)
    
    logger.info("=" * 50)
    logger.info("嵌入式视觉系统启动")
    logger.info("=" * 50)
    logger.info(f"Model: {args.model}")
    logger.info(f"Camera: {args.camera}")
    logger.info(f"Inference threads: {args.threads}")
    logger.info(f"Async mode: {not args.sync}")
    logger.info(f"Data root: {describe_storage_root()}")
    
    try:
        # 初始化视觉管道
        with VisionPipeline(
            model_path=args.model,
            camera_id=args.camera,
            num_inference_threads=args.threads,
            enable_async=not args.sync
        ) as pipeline:
            
            # 视频输出设置
            out_win = "Object Detection"
            cv2.namedWindow(out_win, cv2.WINDOW_NORMAL)
            
            # 视频录制设置（如果需要）
            writer = None
            if args.output:
                output_path = ensure_managed_path(args.output, "videos")
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                frame_size = (
                    pipeline.camera.frame_width,
                    pipeline.camera.frame_height
                )
                writer = cv2.VideoWriter(
                    str(output_path),
                    fourcc,
                    30.0,
                    frame_size
                )
                logger.info(f"Recording to: {output_path}")
            
            logger.info("按 'q' 退出程序")
            
            loop_start = time.time()
            loop_count = 0
            
            # 主处理循环
            while True:
                loop_count += 1
                
                # 处理一帧
                result = pipeline.process_frame()
                
                if not result['success']:
                    logger.warning("Failed to process frame")
                    continue
                
                frame = result['frame']
                metadata = result['metadata']
                
                # 绘制统计信息
                fps_text = f"FPS: {pipeline.stats['avg_fps']:.1f}"
                det_text = f"Detections: {metadata['num_detections']}"
                
                cv2.putText(
                    frame, fps_text,
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 0), 2
                )
                cv2.putText(
                    frame, det_text,
                    (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 0), 2
                )
                
                # 显示帧
                cv2.imshow(out_win, frame)
                
                # 保存视频
                if writer is not None:
                    writer.write(frame)
                
                # 退出检查
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    logger.info("User requested exit")
                    break
                
                # 每 30 帧输出一次统计信息
                if loop_count % 30 == 0:
                    elapsed = time.time() - loop_start
                    fps = 30 / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"[Frame {pipeline.stats['total_frames']}] "
                        f"FPS: {fps:.1f}, "
                        f"Detections: {pipeline.stats['total_detections']}, "
                        f"Inference: {pipeline.stats['inference_time']*1000:.1f}ms"
                    )
                    loop_start = time.time()
                    loop_count = 0
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
    
    finally:
        cv2.destroyAllWindows()
        if writer is not None:
            writer.release()
        logger.info("程序退出")


if __name__ == '__main__':
    main()
