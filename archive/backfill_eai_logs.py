# -*- coding: utf-8 -*-
"""
EAI日志历史数据补录脚本
从EAI服务器读取历史日志，解析报工成功记录并补录到ACC数据库

用法：
    python backfill_eai_logs.py [--start-date 2026-01-01] [--dry-run]

参数：
    --start-date: 起始日期（默认 2026-01-01）
    --end-date: 结束日期（默认 今天）
    --dry-run: 仅解析不插入数据库
    --log-file: 指定单个日志文件（用于测试）
"""

import sys
import os
import re
import json
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass

import paramiko

# 添加当前目录到path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import EAI_SERVER, LOG_FILE_MAPPING, ACC_DATABASE, get_dsn
from log_parser import LogParser, ReportRecord

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backfill.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class SSHClient:
    """SSH客户端封装"""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._client: Optional[paramiko.SSHClient] = None

    def connect(self) -> bool:
        """建立SSH连接"""
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=30
            )
            logger.info(f"SSH连接成功: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"SSH连接失败: {e}")
            return False

    def disconnect(self):
        """断开SSH连接"""
        if self._client:
            self._client.close()
            self._client = None

    def execute(self, command: str, timeout: int = 300) -> Tuple[str, str]:
        """执行命令并返回输出"""
        if not self._client:
            raise RuntimeError("SSH未连接")

        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode('utf-8', errors='ignore')
        err = stderr.read().decode('utf-8', errors='ignore')
        return out, err

    def read_file(self, filepath: str, start_date: Optional[str] = None) -> str:
        """
        读取远程文件内容

        Args:
            filepath: 文件路径
            start_date: 可选的起始日期过滤（格式：YYYY-MM-DD）

        Returns:
            文件内容
        """
        # 对包含空格的路径加引号
        quoted_path = f'"{filepath}"'

        if start_date:
            # 使用grep过滤日期范围，减少传输数据量
            # 匹配 [INFO][2026-01-XX 格式的日志行
            command = f'grep -E "\\[INFO\\]\\[{start_date[:7]}" {quoted_path} 2>/dev/null || cat {quoted_path}'
        else:
            command = f'cat {quoted_path}'

        logger.info(f"执行命令: {command}")
        out, err = self.execute(command, timeout=600)

        if err and 'No such file' in err:
            logger.warning(f"文件不存在: {filepath}")
            return ""

        return out

    def list_log_files(self, log_dir: str) -> List[str]:
        """列出日志目录中的文件"""
        command = f'ls -la "{log_dir}"'
        out, err = self.execute(command)
        logger.info(f"日志目录内容:\n{out}")
        return out.split('\n')


class BackfillDBHandler:
    """补录专用数据库处理器"""

    TABLE_NAME = 'ACC_ERP_REPORT_SUCCESS'

    def __init__(self, schema_name: str):
        self.schema_name = schema_name
        self._schema_config = ACC_DATABASE['schemas'].get(schema_name)
        if not self._schema_config:
            raise ValueError(f"Unknown schema: {schema_name}")
        self._dsn = get_dsn(schema_name)
        self._conn = None
        self._existing_schb_numbers = set()

    def connect(self):
        """连接数据库"""
        import cx_Oracle
        try:
            self._conn = cx_Oracle.connect(
                user=self._schema_config['user'],
                password=self._schema_config['password'],
                dsn=self._dsn,
                encoding='UTF-8'
            )
            logger.info(f"数据库连接成功: {self.schema_name} @ {self._dsn}")
            self._load_existing_records()
            self._ensure_table_structure()
        except cx_Oracle.Error as e:
            logger.error(f"数据库连接失败: {e}")
            raise

    def disconnect(self):
        """断开数据库"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_table_structure(self):
        """确保表结构正确"""
        cursor = self._conn.cursor()

        # 检查表是否存在
        cursor.execute("""
            SELECT COUNT(*) FROM user_tables WHERE table_name = :table_name
        """, {'table_name': self.TABLE_NAME})

        if cursor.fetchone()[0] == 0:
            logger.warning(f"表 {self.TABLE_NAME} 不存在，请先运行监听服务创建表")
            return

        # 检查必要的字段
        required_columns = ['WONO', 'PACKID', 'PARTNO', 'CNT', 'LINE', 'SCHB_NUMBER', 'REPORT_TIME']
        cursor.execute("""
            SELECT column_name FROM user_tab_columns WHERE table_name = :table_name
        """, {'table_name': self.TABLE_NAME})

        existing_columns = {row[0] for row in cursor.fetchall()}
        logger.info(f"现有字段: {existing_columns}")

        missing = set(required_columns) - existing_columns
        if missing:
            logger.warning(f"缺少字段: {missing}")

    def _load_existing_records(self):
        """加载已存在的记录（用于去重）"""
        cursor = self._conn.cursor()
        try:
            cursor.execute(f"SELECT SCHB_NUMBER FROM {self.TABLE_NAME} WHERE SCHB_NUMBER IS NOT NULL")
            self._existing_schb_numbers = {row[0] for row in cursor.fetchall()}
            logger.info(f"已加载 {len(self._existing_schb_numbers)} 条已存在记录")
        except Exception as e:
            logger.warning(f"加载已存在记录失败: {e}")

    def is_duplicate(self, schb_number: str) -> bool:
        """检查是否重复"""
        return schb_number in self._existing_schb_numbers

    def insert_record(self, record: ReportRecord) -> bool:
        """插入单条记录"""
        if self.is_duplicate(record.schb_number):
            logger.debug(f"记录已存在，跳过: {record.schb_number}")
            return False

        cursor = self._conn.cursor()
        try:
            # 使用与eai_log_monitor相同的表结构
            sql = f"""
            INSERT INTO {self.TABLE_NAME}
            (ID, WONO, PACKID, PARTNO, CNT, LINE, SCHB_NUMBER, SOURCE_BILL_NO, REPORT_TIME, IS_SUCCESS, CREATETIME)
            VALUES
            (ACC_ERP_REPT_SUCC_SEQ.NEXTVAL, :wono, :packid, :partno, :cnt, :line, :schb_number, :source_bill_no, :report_time, :is_success, SYSDATE)
            """

            cursor.execute(sql, {
                'wono': record.source_bill_no or 'UNKNOWN',
                'packid': record.lot_number or '',
                'partno': record.product_code or '',
                'cnt': record.qty,
                'line': record.line or '',
                'schb_number': record.schb_number,
                'source_bill_no': record.source_bill_no,
                'report_time': record.report_time,
                'is_success': 1 if record.is_success else 0
            })

            self._conn.commit()
            self._existing_schb_numbers.add(record.schb_number)
            return True

        except Exception as e:
            logger.error(f"插入记录失败: {e}, SCHB={record.schb_number}")
            self._conn.rollback()
            return False

    def insert_records_batch(self, records: List[ReportRecord]) -> int:
        """批量插入记录"""
        success_count = 0
        for record in records:
            if self.insert_record(record):
                success_count += 1
        return success_count


class EAILogBackfiller:
    """EAI日志补录器"""

    def __init__(self, start_date: str, end_date: Optional[str] = None, dry_run: bool = False):
        """
        初始化补录器

        Args:
            start_date: 起始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)，默认为今天
            dry_run: 仅解析不插入
        """
        self.start_date = datetime.strptime(start_date, '%Y-%m-%d')
        self.end_date = datetime.strptime(end_date, '%Y-%m-%d') if end_date else datetime.now()
        self.dry_run = dry_run

        self.ssh_client = SSHClient(
            host=EAI_SERVER['host'],
            port=EAI_SERVER['port'],
            user=EAI_SERVER['user'],
            password=EAI_SERVER['password']
        )

        self.db_handlers: Dict[str, BackfillDBHandler] = {}
        self.stats = {
            'total_lines': 0,
            'parsed_records': 0,
            'inserted_records': 0,
            'duplicate_records': 0,
            'failed_records': 0
        }

    def connect(self):
        """建立所有连接"""
        if not self.ssh_client.connect():
            raise RuntimeError("SSH连接失败")

        if not self.dry_run:
            for schema in ['dpepp1', 'smt2', 'dpeps1']:
                try:
                    handler = BackfillDBHandler(schema)
                    handler.connect()
                    self.db_handlers[schema] = handler
                except Exception as e:
                    logger.warning(f"数据库 {schema} 连接失败: {e}")

    def disconnect(self):
        """断开所有连接"""
        self.ssh_client.disconnect()
        for handler in self.db_handlers.values():
            handler.disconnect()

    def list_available_logs(self):
        """列出可用的日志文件"""
        log_dir = EAI_SERVER['log_dir']
        self.ssh_client.list_log_files(log_dir)

    def process_log_file(self, log_file: str, schema: str) -> List[ReportRecord]:
        """
        处理单个日志文件

        Args:
            log_file: 日志文件相对路径
            schema: 目标数据库schema

        Returns:
            解析出的记录列表
        """
        full_path = f"{EAI_SERVER['log_dir']}{log_file}"
        logger.info(f"处理日志文件: {full_path}")

        # 读取文件内容
        content = self.ssh_client.read_file(full_path, self.start_date.strftime('%Y-%m-%d'))
        if not content:
            logger.warning(f"日志文件为空或不存在: {full_path}")
            return []

        lines = content.split('\n')
        self.stats['total_lines'] += len(lines)
        logger.info(f"读取到 {len(lines)} 行日志")

        # 使用LogParser解析
        parser = LogParser()
        records = []

        for i, line in enumerate(lines):
            if not line.strip():
                continue

            # 检查日期范围
            if not self._is_in_date_range(line):
                continue

            try:
                record = parser.parse_line(line)
                if record and record.is_success:  # 只处理成功记录
                    records.append(record)
                    self.stats['parsed_records'] += 1
                    logger.debug(f"解析到记录: {record.schb_number}, WONO={record.source_bill_no}")
            except Exception as e:
                logger.debug(f"解析行 {i} 失败: {e}")

        logger.info(f"从 {log_file} 解析出 {len(records)} 条成功记录")
        return records

    def _is_in_date_range(self, line: str) -> bool:
        """检查日志行是否在日期范围内"""
        # 匹配日志时间戳 [INFO][2026-01-12 10:30:45.xxx]
        match = re.search(r'\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}', line)
        if not match:
            return True  # 无法解析日期的行默认包含

        try:
            log_date = datetime.strptime(match.group(1), '%Y-%m-%d')
            return self.start_date <= log_date <= self.end_date
        except ValueError:
            return True

    def run(self):
        """执行补录"""
        logger.info("=" * 60)
        logger.info(f"EAI日志历史补录开始")
        logger.info(f"日期范围: {self.start_date.strftime('%Y-%m-%d')} ~ {self.end_date.strftime('%Y-%m-%d')}")
        logger.info(f"模式: {'仅解析(dry-run)' if self.dry_run else '解析并插入'}")
        logger.info("=" * 60)

        try:
            self.connect()

            # 列出日志目录
            self.list_available_logs()

            # 处理每个日志文件
            for log_file, config in LOG_FILE_MAPPING.items():
                schema = config['schema']
                description = config['description']

                logger.info(f"\n处理 {description} ({log_file}) -> {schema}")

                records = self.process_log_file(log_file, schema)

                if not records:
                    continue

                if self.dry_run:
                    logger.info(f"[DRY-RUN] 将插入 {len(records)} 条记录到 {schema}")
                    for r in records[:5]:  # 只显示前5条
                        logger.info(f"  - SCHB={r.schb_number}, WONO={r.source_bill_no}, QTY={r.qty}, LINE={r.line}")
                    if len(records) > 5:
                        logger.info(f"  ... 还有 {len(records)-5} 条")
                else:
                    # 实际插入
                    if schema in self.db_handlers:
                        handler = self.db_handlers[schema]
                        for record in records:
                            if handler.is_duplicate(record.schb_number):
                                self.stats['duplicate_records'] += 1
                            elif handler.insert_record(record):
                                self.stats['inserted_records'] += 1
                            else:
                                self.stats['failed_records'] += 1
                    else:
                        logger.warning(f"没有可用的数据库连接: {schema}")

        finally:
            self.disconnect()

        # 输出统计
        logger.info("\n" + "=" * 60)
        logger.info("补录统计:")
        logger.info(f"  总日志行数: {self.stats['total_lines']}")
        logger.info(f"  解析记录数: {self.stats['parsed_records']}")
        logger.info(f"  插入记录数: {self.stats['inserted_records']}")
        logger.info(f"  重复记录数: {self.stats['duplicate_records']}")
        logger.info(f"  失败记录数: {self.stats['failed_records']}")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='EAI日志历史数据补录')
    parser.add_argument('--start-date', default='2026-01-01', help='起始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)，默认今天')
    parser.add_argument('--dry-run', action='store_true', help='仅解析不插入数据库')
    parser.add_argument('--list-logs', action='store_true', help='仅列出日志文件')

    args = parser.parse_args()

    backfiller = EAILogBackfiller(
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run
    )

    if args.list_logs:
        backfiller.ssh_client.connect()
        backfiller.list_available_logs()
        backfiller.ssh_client.disconnect()
    else:
        backfiller.run()


if __name__ == '__main__':
    main()
