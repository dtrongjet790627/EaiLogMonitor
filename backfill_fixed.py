# -*- coding: utf-8 -*-
"""
EAI日志历史数据补录脚本（修正版）
使用日志中的实际时间戳作为REPORT_TIME和CREATETIME

用法：
    python backfill_fixed.py [--start-date 2025-12-01] [--dry-run]
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
import oracledb
oracledb.init_oracle_client(lib_dir=r"D:\Software_Space\instantclient_23_0")
import oracledb as cx_Oracle

# 添加当前目录到path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import EAI_SERVER, LOG_FILE_MAPPING, ACC_DATABASE, get_dsn

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backfill_fixed.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class ReportRecord:
    """报工记录"""
    schb_number: str
    source_bill_no: str
    qty: float
    product_code: str
    lot_number: str
    line: str
    report_time: datetime  # 日志中的时间戳
    is_success: bool


class FixedLogParser:
    """修正版日志解析器 - 确保使用日志时间戳"""

    # BUG-021 修复：改为匹配任意日志级别 \[\w+\]，而非硬编码 \[INFO\]
    LOG_TIMESTAMP_PATTERN = re.compile(
        r'\[\w+\]\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\.\d+\]'
    )

    # BUG-005 修复（同 log_parser.py）：贪婪匹配避免嵌套数组截断
    TRIGGER_DATA_PATTERN = re.compile(
        r'db\s+trigger\s+get\s+data:\s*(\[.*\])',
        re.IGNORECASE | re.DOTALL
    )

    KINGDEE_RESPONSE_PATTERN = re.compile(
        r'kingdee\s+response\s+json\s*:\s*(\{.*)',
        re.IGNORECASE | re.DOTALL
    )

    # BUG-020 新增：用于识别 request 行，从而缓存当前 WONO 实现精确配对
    KINGDEE_REQUEST_PATTERN = re.compile(
        r'kingdee\s+request\s+json\s*:\s*(\{.*)',
        re.IGNORECASE | re.DOTALL
    )

    SUCCESS_PATTERN = re.compile(r'"IsSuccess"\s*:\s*true', re.IGNORECASE)

    def __init__(self):
        self._trigger_queues: Dict[str, list] = {}  # {WONO: [trigger, ...]}
        self._current_timestamp = None
        # BUG-020 新增：缓存当前 request 行解析出的 WONO，用于精确匹配 trigger 队列
        self._current_wono: Optional[str] = None

    def parse_line(self, line: str) -> Optional[ReportRecord]:
        """解析单行日志"""
        try:
            line = line.strip()
            if not line:
                return None

            # 提取时间戳
            ts_match = self.LOG_TIMESTAMP_PATTERN.search(line)
            if ts_match:
                try:
                    self._current_timestamp = datetime.strptime(ts_match.group(1), '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

            # 检查触发器数据
            trigger_match = self.TRIGGER_DATA_PATTERN.search(line)
            if trigger_match:
                self._handle_trigger(trigger_match.group(1))
                return None

            # BUG-020 新增：检查 request 行，缓存 WONO 用于后续精确配对
            req_match = self.KINGDEE_REQUEST_PATTERN.search(line)
            if req_match:
                try:
                    req_data = json.loads(req_match.group(1))
                    wono = self._extract_wono_from_request(req_data)
                    if wono:
                        self._current_wono = wono
                        logger.debug(f"缓存 request WONO: {wono}")
                except Exception:
                    pass
                return None

            # 检查响应
            resp_match = self.KINGDEE_RESPONSE_PATTERN.search(line)
            if resp_match:
                return self._handle_response(resp_match.group(1))

            return None
        except Exception as e:
            return None

    def _handle_trigger(self, json_str: str):
        """处理触发器数据"""
        try:
            data_list = json.loads(json_str)
            if data_list and isinstance(data_list, list):
                trigger = data_list[0]
                wono = trigger.get('WONO', '')
                if not wono:
                    return
                if wono not in self._trigger_queues:
                    self._trigger_queues[wono] = []
                self._trigger_queues[wono].append(trigger)
                logger.debug(f"入队触发器: WONO={wono}, PACKID={trigger.get('PACKID')}, 队列深度={len(self._trigger_queues[wono])}")
        except:
            pass

    def _handle_response(self, json_str: str) -> Optional[ReportRecord]:
        """处理响应"""
        if not self._trigger_queues:
            self._current_wono = None
            return None

        if not self.SUCCESS_PATTERN.search(json_str):
            self._current_wono = None
            return None

        try:
            resp_data = json.loads(json_str)
            schb_number = self._extract_schb(resp_data)
            if not schb_number:
                self._current_wono = None
                return None

            # BUG-020 修复：优先用 _current_wono 精确匹配 trigger 队列，无法精确匹配时再 FIFO 兜底
            trigger = None
            if self._current_wono and self._current_wono in self._trigger_queues:
                queue = self._trigger_queues[self._current_wono]
                if queue:
                    trigger = queue.pop(0)
                    if not queue:
                        del self._trigger_queues[self._current_wono]
                    logger.debug(f"精确匹配 trigger: WONO={self._current_wono}")
            if not trigger:
                trigger = self._pop_oldest_trigger()  # 兜底：FIFO
                if trigger:
                    logger.debug(f"兜底 FIFO 取 trigger: WONO={trigger.get('WONO', '')}")
            self._current_wono = None  # 消费完毕，清空

            if not trigger:
                return None

            record = ReportRecord(
                schb_number=schb_number,
                source_bill_no=trigger.get('WONO', ''),
                qty=float(trigger.get('CNT', 0) or 0),
                product_code=trigger.get('PARTNO', ''),
                lot_number=trigger.get('PACKID', ''),
                line=trigger.get('LINE', ''),
                report_time=self._current_timestamp or datetime.now(),
                is_success=True
            )

            logger.info(f"解析成功: SCHB={schb_number}, WONO={record.source_bill_no}, TIME={record.report_time}")
            return record

        except Exception as e:
            self._current_wono = None
            logger.debug(f"解析响应失败: {e}")
            return None

    def _pop_oldest_trigger(self) -> Optional[dict]:
        """按 FIFO 取出最早入队的 trigger"""
        for wono, queue in list(self._trigger_queues.items()):
            if queue:
                trigger = queue.pop(0)
                if not queue:
                    del self._trigger_queues[wono]
                return trigger
        return None

    def _extract_wono_from_request(self, data: dict) -> Optional[str]:
        """
        BUG-020 辅助方法：从 request JSON 中提取 WONO/FBillNo 字段

        参考 log_parser.py 的 _extract_source_bill_no 实现，
        按优先级查找 FMoBillNo / FSrcBillNo / FBillNo / WONO 等字段

        Args:
            data: 已解析的 request JSON 字典

        Returns:
            WONO 字符串，找不到返回 None
        """
        possible_keys = ['FMoBillNo', 'FSrcBillNo', 'FBillNo', 'WONO', 'BillNo', 'schb_number']

        # 如果有 _parsed_data 嵌套，优先从那里找
        search_data = data.get('_parsed_data', data)

        # 根层级查找
        for key in possible_keys:
            val = search_data.get(key)
            if val:
                return str(val)

        # data 字段可能是嵌套 JSON 字符串
        if 'data' in data:
            try:
                inner = json.loads(data['data']) if isinstance(data['data'], str) else data['data']
                for key in possible_keys:
                    val = inner.get(key)
                    if val:
                        return str(val)
            except Exception:
                pass

        # Model 层
        model = search_data.get('Model')
        if isinstance(model, dict):
            for key in possible_keys:
                val = model.get(key)
                if val:
                    return str(val)

        return None

    def _extract_schb(self, data: dict) -> Optional[str]:
        """提取汇报单号"""
        if 'Result' in data and isinstance(data['Result'], dict):
            result = data['Result']
            # 首先直接在Result中查找Number
            for key in ['Number', 'FBillNo', 'BillNo']:
                if key in result:
                    return str(result[key])
            # 然后在ResponseStatus中查找
            if 'ResponseStatus' in result:
                resp = result['ResponseStatus']
                for key in ['Number', 'FBillNo', 'BillNo']:
                    if key in resp:
                        return str(resp[key])
        # 直接在根级别查找
        for key in ['Number', 'FBillNo', 'BillNo']:
            if key in data:
                return str(data[key])
        return None


class BackfillHandler:
    """补录处理器"""

    TABLE_NAME = 'ACC_ERP_REPORT_SUCCESS'

    def __init__(self, schema: str):
        self.schema = schema
        self._config = ACC_DATABASE['schemas'].get(schema)
        self._dsn = get_dsn(schema)
        self._conn = None
        self._existing = set()

    def connect(self):
        """连接数据库"""
        self._conn = cx_Oracle.connect(
            user=self._config['user'],
            password=self._config['password'],
            dsn=self._dsn
        )
        logger.info(f"数据库连接成功: {self.schema}")
        self._load_existing()

    def disconnect(self):
        """断开连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _load_existing(self):
        """加载已存在记录"""
        cursor = self._conn.cursor()
        cursor.execute(f"SELECT SCHB_NUMBER FROM {self.TABLE_NAME} WHERE SCHB_NUMBER IS NOT NULL")
        self._existing = {row[0] for row in cursor.fetchall()}
        logger.info(f"已加载 {len(self._existing)} 条现有记录")

    def is_duplicate(self, schb: str) -> bool:
        """检查重复"""
        return schb in self._existing

    def insert_record(self, record: ReportRecord) -> bool:
        """插入记录 - 使用日志时间作为REPORT_TIME和CREATETIME"""
        if self.is_duplicate(record.schb_number):
            return False

        cursor = self._conn.cursor()
        try:
            # 使用日志时间作为REPORT_TIME和CREATETIME
            sql = f"""
            INSERT INTO {self.TABLE_NAME}
            (ID, WONO, PACKID, PARTNO, CNT, LINE, SCHB_NUMBER, SOURCE_BILL_NO, REPORT_TIME, IS_SUCCESS, CREATETIME)
            VALUES
            (ACC_ERP_REPT_SUCC_SEQ.NEXTVAL, :wono, :packid, :partno, :cnt, :line, :schb, :src, :rtime, 1, :ctime)
            """

            cursor.execute(sql, {
                'wono': record.source_bill_no,
                'packid': record.lot_number,
                'partno': record.product_code,
                'cnt': record.qty,
                'line': record.line,
                'schb': record.schb_number,
                'src': record.source_bill_no,
                'rtime': record.report_time,
                'ctime': record.report_time  # 使用日志时间
            })

            self._conn.commit()
            self._existing.add(record.schb_number)
            return True

        except Exception as e:
            logger.error(f"插入失败: {e}, SCHB={record.schb_number}")
            self._conn.rollback()
            return False


class SSHClient:
    """SSH客户端"""

    def __init__(self):
        self._client = None

    def connect(self):
        """连接"""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=EAI_SERVER['host'],
            port=EAI_SERVER['port'],
            username=EAI_SERVER['user'],
            password=EAI_SERVER['password'],
            timeout=30
        )
        logger.info(f"SSH连接成功: {EAI_SERVER['host']}:{EAI_SERVER['port']}")

    def disconnect(self):
        """断开"""
        if self._client:
            self._client.close()

    def read_file(self, filepath: str) -> str:
        """读取文件"""
        quoted = f'"{filepath}"'
        cmd = f'cat {quoted} 2>/dev/null'
        stdin, stdout, stderr = self._client.exec_command(cmd, timeout=600)
        return stdout.read().decode('utf-8', errors='ignore')

    def read_gz_file(self, filepath: str) -> str:
        """读取gz压缩文件"""
        quoted = f'"{filepath}"'
        cmd = f'zcat {quoted} 2>/dev/null'
        stdin, stdout, stderr = self._client.exec_command(cmd, timeout=600)
        return stdout.read().decode('utf-8', errors='ignore')

    def list_archive_files(self, log_file_base: str) -> list:
        """列出指定日志文件对应的所有.gz归档文件，按时间排序
        log_file_base: 日志文件基础名（不含.log后缀），如 'FLOW_SMT\\MID-Line2MES报工接口'
        """
        # 取文件名部分（去掉路径前缀中的反斜杠路径），反斜杠是Linux文件名的一部分
        # log_file_base 例如 'FLOW_SMT\MID-Line2MES报工接口'
        # ls /var/eai/logs/ 列出的文件名包含反斜杠，如 'FLOW_SMT\MID-Line2MES报工接口-{ts}.log.gz'
        # 用basename_part（纯文件名关键字）来grep，避免路径问题
        basename_part = os.path.basename(log_file_base.replace('\\', '/'))
        cmd = f'ls -1 /var/eai/logs/ | grep -F "{basename_part}" | grep "\\.gz$" | sort'
        stdin, stdout, stderr = self._client.exec_command(cmd, timeout=30)
        files = stdout.read().decode('utf-8', errors='ignore').strip().split('\n')
        return [f'/var/eai/logs/{f}' for f in files if f.strip()]


def main():
    parser = argparse.ArgumentParser(description='EAI日志历史数据补录(修正版)')
    parser.add_argument('--start-date', default='2025-12-01', help='起始日期')
    parser.add_argument('--end-date', help='结束日期')
    parser.add_argument('--dry-run', action='store_true', help='仅解析不插入')
    parser.add_argument('--schema', help='只处理指定schema (dpepp1/smt2/dpeps1)，不指定则处理全部')

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d') if args.end_date else datetime.now()

    logger.info("=" * 60)
    logger.info("EAI日志历史补录开始 (修正版 - 使用日志时间戳)")
    logger.info(f"日期范围: {start_date.date()} ~ {end_date.date()}")
    logger.info(f"模式: {'仅解析' if args.dry_run else '解析并插入'}")
    logger.info("=" * 60)

    ssh = SSHClient()
    ssh.connect()

    db_handlers = {}
    if not args.dry_run:
        schemas_to_connect = [args.schema] if args.schema else ['dpepp1', 'smt2', 'dpeps1']
        for schema in schemas_to_connect:
            try:
                handler = BackfillHandler(schema)
                handler.connect()
                db_handlers[schema] = handler
            except Exception as e:
                logger.warning(f"数据库 {schema} 连接失败: {e}")

    stats = {'total': 0, 'parsed': 0, 'inserted': 0, 'duplicate': 0, 'failed': 0}

    try:
        for log_file, config in LOG_FILE_MAPPING.items():
            schema = config['schema']
            desc = config['description']

            # schema过滤
            if args.schema and schema != args.schema:
                logger.info(f"跳过 {desc} (schema={schema})")
                continue

            logger.info(f"\n处理 {desc} ({log_file}) -> {schema}")

            # 构建要读取的文件列表（先归档后当前）
            files_to_read = []

            # 查找归档文件（按时间排序）
            log_base = log_file.replace('.log', '')  # 去掉 .log 后缀，如 'FLOW_SMT\MID-Line2MES报工接口'
            archive_files = ssh.list_archive_files(log_base)
            if archive_files:
                logger.info(f"发现 {len(archive_files)} 个归档文件")
                files_to_read.extend([(f, True) for f in archive_files])  # True = is_gz

            # 当前日志文件
            full_path = EAI_SERVER['log_dir'] + log_file
            files_to_read.append((full_path, False))  # False = not gz

            all_records = []
            total_lines = 0

            # BUG-022 修复：parser 实例移到文件循环外，所有归档文件共享同一解析状态，
            # 避免跨文件边界时 trigger 丢失（trigger 在上一个文件末尾，response 在下一个文件开头）
            log_parser = FixedLogParser()

            for file_path, is_gz in files_to_read:
                if is_gz:
                    content = ssh.read_gz_file(file_path)
                else:
                    content = ssh.read_file(file_path)

                if not content:
                    logger.warning(f"文件为空或不存在: {file_path}")
                    continue

                lines = content.split('\n')
                total_lines += len(lines)
                logger.info(f"  {file_path}: 读取 {len(lines)} 行")

                for line in lines:
                    if not line.strip():
                        continue

                    # BUG-019 修复：移除行级别的日期过滤（会导致 trigger 行不入队但 response 仍配对）
                    # 所有行都传给 parser（trigger 无条件入队），只对最终 record 的 report_time 过滤
                    record = log_parser.parse_line(line)
                    if record and record.is_success:
                        if start_date <= record.report_time <= end_date + timedelta(days=1):
                            all_records.append(record)
                            stats['parsed'] += 1

            stats['total'] += total_lines
            records = all_records
            logger.info(f"从所有文件共解析出 {len(records)} 条成功记录")

            if args.dry_run:
                logger.info(f"[DRY-RUN] 将插入 {len(records)} 条记录到 {schema}")
                for r in records[:5]:
                    logger.info(f"  SCHB={r.schb_number}, WONO={r.source_bill_no}, TIME={r.report_time}, LINE={r.line}")
                if len(records) > 5:
                    logger.info(f"  ... 还有 {len(records)-5} 条")
            else:
                if schema in db_handlers:
                    handler = db_handlers[schema]
                    for record in records:
                        if handler.is_duplicate(record.schb_number):
                            stats['duplicate'] += 1
                        elif handler.insert_record(record):
                            stats['inserted'] += 1
                        else:
                            stats['failed'] += 1

    finally:
        ssh.disconnect()
        for handler in db_handlers.values():
            handler.disconnect()

    logger.info("\n" + "=" * 60)
    logger.info("补录统计:")
    logger.info(f"  总日志行数: {stats['total']}")
    logger.info(f"  解析记录数: {stats['parsed']}")
    logger.info(f"  插入记录数: {stats['inserted']}")
    logger.info(f"  重复记录数: {stats['duplicate']}")
    logger.info(f"  失败记录数: {stats['failed']}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
