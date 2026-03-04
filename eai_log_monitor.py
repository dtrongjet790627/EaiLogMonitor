# -*- coding: utf-8 -*-
"""
EAI日志监听服务 - 主程序
通过SSH连接EAI服务器，监听报工日志并插入ACC数据库
"""

import sys
import signal
import logging
import threading
import time
import queue
from datetime import datetime
from typing import Dict, Optional

import paramiko

from config import (
    EAI_SERVER, LOG_FILE_MAPPING, SERVICE_CONFIG,
    get_log_file_path, ENV
)
from log_parser import LogParser, ReportRecord
from db_handler import DBHandler, DBHandlerManager

# 配置日志
logging.basicConfig(
    level=getattr(logging, SERVICE_CONFIG['log_level']),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('eai_monitor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class SSHLogMonitor:
    """SSH日志监听器"""

    def __init__(self, log_file: str, schema_name: str, description: str):
        """
        初始化监听器

        Args:
            log_file: 日志文件相对路径
            schema_name: 数据库模式名称
            description: 产线描述
        """
        self.log_file = log_file
        self.schema_name = schema_name
        self.description = description
        self.full_path = get_log_file_path(log_file)

        self._ssh_client: Optional[paramiko.SSHClient] = None
        self._channel = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._parser = LogParser()
        self._record_queue: queue.Queue[ReportRecord] = queue.Queue()

    def start(self):
        """启动监听"""
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"启动监听: {self.description} ({self.log_file})")

    def stop(self):
        """停止监听"""
        self._running = False
        if self._channel:
            self._channel.close()
        if self._ssh_client:
            self._ssh_client.close()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"停止监听: {self.description}")

    def get_records(self) -> list[ReportRecord]:
        """获取解析到的记录（非阻塞）"""
        records = []
        while True:
            try:
                record = self._record_queue.get_nowait()
                records.append(record)
            except queue.Empty:
                break
        return records

    def _connect_ssh(self) -> bool:
        """建立SSH连接"""
        try:
            self._ssh_client = paramiko.SSHClient()
            self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh_client.connect(
                hostname=EAI_SERVER['host'],
                port=EAI_SERVER['port'],
                username=EAI_SERVER['user'],
                password=EAI_SERVER['password'],
                timeout=30
            )
            logger.info(f"SSH连接成功: {EAI_SERVER['host']}:{EAI_SERVER['port']}")
            return True
        except Exception as e:
            logger.error(f"SSH连接失败: {e}")
            return False

    def _monitor_loop(self):
        """监听循环"""
        while self._running:
            try:
                # 建立SSH连接
                if not self._connect_ssh():
                    logger.warning(f"连接失败，{SERVICE_CONFIG['reconnect_interval']}秒后重试...")
                    time.sleep(SERVICE_CONFIG['reconnect_interval'])
                    continue

                # BUG-016 修复：重连后先补读最近1000行，避免断开期间日志丢失
                catchup_command = f'tail -1000 "{self.full_path}"'
                logger.info(f"补读历史日志: {catchup_command}")
                _, catchup_stdout, _ = self._ssh_client.exec_command(catchup_command)
                catchup_data = catchup_stdout.read().decode('utf-8', errors='ignore')
                for catchup_line in catchup_data.splitlines():
                    self._process_line(catchup_line)
                logger.info(f"补读历史日志完成，共 {len(catchup_data.splitlines())} 行")

                # 执行tail -F命令（路径需要引号包裹，因为包含空格）
                command = f'tail -F "{self.full_path}"'
                logger.info(f"执行命令: {command}")

                # BUG-017 修复：去掉 get_pty=True，避免 stderr 混入 stdout
                stdin, stdout, stderr = self._ssh_client.exec_command(
                    command
                )

                # 持续读取输出
                self._channel = stdout.channel
                buffer = ""

                while self._running and not self._channel.closed:
                    if self._channel.recv_ready():
                        try:
                            # BUG-018 修复：缓冲区从 4096 扩大到 65536（64KB），减少高频日志积压
                            data = self._channel.recv(65536).decode('utf-8', errors='ignore')
                            buffer += data

                            # 按行处理
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                self._process_line(line)

                        except Exception as e:
                            logger.warning(f"读取数据失败: {e}")
                            break

                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"监听异常: {e}")

            finally:
                if self._ssh_client:
                    self._ssh_client.close()
                    self._ssh_client = None

            if self._running:
                logger.warning(f"连接断开，{SERVICE_CONFIG['reconnect_interval']}秒后重连...")
                time.sleep(SERVICE_CONFIG['reconnect_interval'])

    def _process_line(self, line: str):
        """处理日志行"""
        try:
            record = self._parser.parse_line(line)
            if record:
                self._record_queue.put(record)
                logger.debug(f"解析到记录: {record.schb_number}")
        except Exception as e:
            logger.warning(f"处理日志行失败: {e}")


class EAILogMonitorService:
    """EAI日志监听服务"""

    def __init__(self):
        self._monitors: Dict[str, SSHLogMonitor] = {}
        self._db_manager = DBHandlerManager()
        self._running = False
        self._stats = {
            'start_time': None,
            'total_records': 0,
            'inserted_records': 0,
            'duplicate_records': 0
        }

    def start(self):
        """启动服务"""
        logger.info("=" * 60)
        logger.info(f"EAI日志监听服务启动 (环境: {ENV})")
        logger.info("=" * 60)

        self._running = True
        self._stats['start_time'] = datetime.now()

        # 创建监听器
        for log_file, config in LOG_FILE_MAPPING.items():
            monitor = SSHLogMonitor(
                log_file=log_file,
                schema_name=config['schema'],
                description=config['description']
            )
            self._monitors[log_file] = monitor
            monitor.start()

        # 启动数据处理循环
        self._process_loop()

    def stop(self):
        """停止服务"""
        logger.info("正在停止服务...")
        self._running = False

        # 停止所有监听器
        for monitor in self._monitors.values():
            monitor.stop()

        # 关闭数据库连接
        self._db_manager.close_all()

        # 输出统计信息
        self._print_stats()
        logger.info("服务已停止")

    def _process_loop(self):
        """数据处理循环"""
        batch_records: Dict[str, list[ReportRecord]] = {
            schema: [] for schema in ['dpepp1', 'smt2', 'dpeps1']
        }
        last_insert_time = time.time()

        while self._running:
            try:
                # 收集各监听器的记录
                for log_file, monitor in self._monitors.items():
                    records = monitor.get_records()
                    if records:
                        schema = LOG_FILE_MAPPING[log_file]['schema']
                        batch_records[schema].extend(records)
                        self._stats['total_records'] += len(records)

                # 检查是否需要批量插入
                current_time = time.time()
                should_insert = False

                # 条件1：达到批量阈值
                for records in batch_records.values():
                    if len(records) >= SERVICE_CONFIG['batch_insert_size']:
                        should_insert = True
                        break

                # 条件2：超时
                if current_time - last_insert_time >= SERVICE_CONFIG['batch_insert_timeout']:
                    should_insert = True

                # 执行插入
                if should_insert:
                    for schema, records in batch_records.items():
                        if records:
                            try:
                                handler = self._db_manager.get_handler(schema)
                                inserted = handler.insert_records_batch(records)
                                self._stats['inserted_records'] += inserted
                                self._stats['duplicate_records'] += len(records) - inserted
                                batch_records[schema] = []  # 只有成功才清空
                            except Exception as e:
                                logger.error(f"插入数据库失败 ({schema}): {e}")
                                # 不清空，下次循环继续重试

                    last_insert_time = current_time

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"处理循环异常: {e}")
                time.sleep(1)

    def _print_stats(self):
        """输出统计信息"""
        if self._stats['start_time']:
            duration = datetime.now() - self._stats['start_time']
            logger.info("=" * 60)
            logger.info("服务运行统计:")
            logger.info(f"  运行时长: {duration}")
            logger.info(f"  解析记录: {self._stats['total_records']}")
            logger.info(f"  插入记录: {self._stats['inserted_records']}")
            logger.info(f"  重复记录: {self._stats['duplicate_records']}")
            logger.info("=" * 60)


def main():
    """主函数"""
    service = EAILogMonitorService()

    # 注册信号处理
    def signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，准备停止服务...")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        service.start()
    except KeyboardInterrupt:
        service.stop()
    except Exception as e:
        logger.error(f"服务异常: {e}")
        service.stop()
        sys.exit(1)


if __name__ == '__main__':
    main()
