# -*- coding: utf-8 -*-
"""
EAI日志监听服务 - 日志解析模块
负责解析EAI日志中的报工请求和响应

设计原则：
- EAI按流程串行处理：trigger → request → response
- 每个请求必须对应一个响应（成功或失败）
- 使用"当前请求"模式，确保请求-响应精确配对
- 产线(LINE)直接从触发器数据中提取，不做推断
"""

import re
import json
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TriggerData:
    """触发器数据类 - 从db trigger get data中提取"""
    line: str                  # 产线（LINE字段）
    pack_id: str               # 批次号（PACKID字段）
    wono: str                  # 工单号（WONO字段）
    cnt: str                   # 数量（CNT字段）
    part_no: str               # 料号（PARTNO字段）
    raw_data: str              # 原始JSON数据


@dataclass
class ReportRecord:
    """报工记录数据类"""
    schb_number: str           # 汇报单号（从响应中获取，系统生成的唯一编号）
    source_bill_no: str        # 源单号（请求中的FMoBillNo，用于追溯）
    qty: float                 # 报工数量
    product_code: str          # 产品编码
    process_code: str          # 工序编码
    report_time: datetime      # 报工时间
    worker_code: str           # 报工人员编码
    lot_number: str            # 批次号（FLot.FNumber）
    line: str                  # 产线（从触发器数据中提取）
    raw_request: str           # 原始请求JSON
    raw_response: str          # 原始响应JSON
    is_success: bool           # 是否成功
    error_message: str = ''    # 错误信息（失败时填充）


class LogParser:
    """
    EAI日志解析器

    采用"触发器 → 请求 → 响应"流程确保精确配对：
    1. 收到触发器数据(db trigger get data)时，缓存LINE等信息
    2. 收到请求时，关联触发器数据，设为当前请求
    3. 收到响应时，与当前请求配对
    4. 配对完成后清空当前请求和触发器数据
    """

    # 日志行模式
    LOG_LINE_PATTERN = re.compile(
        r'\[(\w+)\]\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\.\d+\]\[.*?\]\[.*?\]\s*(.*)',
        re.DOTALL
    )

    # 触发器数据标识 - 匹配 db trigger get data:[{...}]
    TRIGGER_DATA_PATTERN = re.compile(
        r'db\s+trigger\s+get\s+data:\s*(\[.*?\])',
        re.IGNORECASE | re.DOTALL
    )

    # kingdee请求标识
    KINGDEE_REQUEST_PATTERN = re.compile(
        r'kingdee\s+request\s+json\s*:\s*(\{.*)',
        re.IGNORECASE | re.DOTALL
    )

    # kingdee响应标识
    KINGDEE_RESPONSE_PATTERN = re.compile(
        r'kingdee\s+response\s+json\s*:\s*(\{.*)',
        re.IGNORECASE | re.DOTALL
    )

    # 成功标识
    SUCCESS_PATTERN = re.compile(
        r'"IsSuccess"\s*:\s*true',
        re.IGNORECASE
    )

    # 失败标识
    FAILURE_PATTERN = re.compile(
        r'"IsSuccess"\s*:\s*false',
        re.IGNORECASE
    )

    # Lua错误标识 - 匹配 run error: call lua error:
    LUA_ERROR_PATTERN = re.compile(
        r'run\s+error:\s+call\s+lua\s+error:.*?(\{.*)',
        re.IGNORECASE | re.DOTALL
    )

    # 从kingdee响应中提取错误信息 - Errors数组中的Message
    ERROR_MESSAGE_PATTERN = re.compile(
        r'"Message"\s*:\s*"([^"]+)"',
        re.IGNORECASE
    )

    # 从截断JSON中提取关键字段的正则（用于JSON解析失败时）
    # 支持普通引号"和转义引号\"两种格式
    # 工单号格式: 2-4个大写字母 + 可选短横线 + 8-9位数字 (如 EPS26010801, SMT-226010703, MID-226010703)
    FIELD_PATTERNS = {
        'FMoBillNo': re.compile(r'FMoBillNo[\\\"]*:[\\\"]*([A-Z]{2,4}-?\d{8,9})'),
        'FSrcBillNo': re.compile(r'FSrcBillNo[\\\"]*:[\\\"]*([A-Z]{2,4}-?\d{8,9})'),
        'FFinishQty': re.compile(r'FFinishQty[\\\"]*:(\d+(?:\.\d+)?)'),
        'FQuaQty': re.compile(r'FQuaQty[\\\"]*:(\d+(?:\.\d+)?)'),
        'FMaterialId_FNumber': re.compile(r'FMaterialId[\\\"]*:\{[\\\"]*FNumber[\\\"]*:[\\\"]*([A-Z0-9.\-]+)'),
        'FLot_FNumber': re.compile(r'FLot[\\\"]*:\{[\\\"]*FNumber[\\\"]*:[\\\"]*(\d{8}[A-Z]\d{7})'),  # 批次号格式: 20260111E2700326
        'FDate': re.compile(r'FDate[\\\"]*:[\\\"]*(\d{4}-\d{2}-\d{2})'),
    }

    # 注意：产线信息直接从触发器数据(db trigger get data)的LINE字段提取
    # 不再使用工单号前缀推断或source字段映射

    def __init__(self):
        """初始化解析器"""
        # 当前触发器数据（从db trigger get data中提取）
        self._current_trigger: Optional[TriggerData] = None

        # 当前待配对的请求（只保留一个，确保精确配对）
        # (时间, 数据, 源单号, 产线)
        self._current_request: Optional[Tuple[datetime, dict, str, str]] = None

    def _handle_trigger_data(self, json_str: str) -> None:
        """
        处理触发器数据（db trigger get data）

        从触发器JSON中提取LINE、PACKID、WONO等字段并缓存
        触发器数据格式：[{"CNT":"16","LINE":"DP EPS1","PACKID":"20251208E2700122","PARTNO":"H25.910.002","WONO":"EPS25120304"}]

        Args:
            json_str: 触发器JSON数组字符串
        """
        try:
            data_list = json.loads(json_str)
            if not data_list or not isinstance(data_list, list):
                logger.warning(f"触发器数据格式错误: {json_str[:100]}")
                return

            # 取第一条数据（通常只有一条）
            data = data_list[0]

            trigger = TriggerData(
                line=data.get('LINE', ''),
                pack_id=data.get('PACKID', ''),
                wono=data.get('WONO', ''),
                cnt=data.get('CNT', ''),
                part_no=data.get('PARTNO', ''),
                raw_data=json_str
            )

            # 覆盖之前的触发器数据
            if self._current_trigger:
                logger.debug(f"覆盖未使用的触发器数据: {self._current_trigger.wono}")

            self._current_trigger = trigger
            logger.info(f"缓存触发器数据: LINE={trigger.line}, WONO={trigger.wono}, PACKID={trigger.pack_id}")

        except json.JSONDecodeError as e:
            logger.warning(f"触发器JSON解析失败: {e}, 内容: {json_str[:100]}")
        except Exception as e:
            logger.warning(f"处理触发器数据失败: {e}")

    def parse_line(self, line: str) -> Optional[ReportRecord]:
        """
        解析单行日志

        处理流程：
        1. 检查是否为触发器数据(db trigger get data) -> 缓存LINE等信息
        2. 检查是否为kingdee请求 -> 关联触发器数据并缓存
        3. 检查是否为kingdee响应 -> 与请求配对并返回记录

        Args:
            line: 日志行内容

        Returns:
            解析成功返回ReportRecord，否则返回None
        """
        try:
            line = line.strip()
            if not line:
                return None

            # 解析日志时间和内容
            timestamp = None
            match = self.LOG_LINE_PATTERN.match(line)
            if match:
                level, time_str, content = match.groups()
                try:
                    timestamp = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    timestamp = datetime.now()
            else:
                content = line
                timestamp = datetime.now()

            # 步骤1：检查是否为Lua错误（优先级最高）
            lua_error_match = self.LUA_ERROR_PATTERN.search(line)
            if lua_error_match:
                return self._handle_lua_error(timestamp, lua_error_match.group(1), line)

            # 步骤2：检查是否为触发器数据
            trigger_match = self.TRIGGER_DATA_PATTERN.search(line)
            if trigger_match:
                self._handle_trigger_data(trigger_match.group(1))
                return None

            # 步骤3：检查是否为kingdee请求
            req_match = self.KINGDEE_REQUEST_PATTERN.search(content)
            if req_match:
                self._handle_request(timestamp, req_match.group(1))
                return None

            # 步骤4：检查是否为kingdee响应
            resp_match = self.KINGDEE_RESPONSE_PATTERN.search(content)
            if resp_match:
                return self._handle_response(timestamp, resp_match.group(1))

            return None

        except Exception as e:
            logger.warning(f"解析日志行失败: {e}, 内容: {line[:100]}...")
            return None

    def _handle_request(self, timestamp: datetime, json_str: str):
        """
        处理kingdee请求

        采用"触发器 + 当前请求"模式：
        - 从当前触发器数据中获取LINE产线信息
        - 新请求会覆盖之前未完成的请求
        - 确保每个响应只能匹配到紧邻它的那个请求
        - 支持处理截断的JSON（EAI日志会截断过长的JSON）

        Args:
            timestamp: 日志时间
            json_str: 请求JSON字符串
        """
        data = None
        source_bill_no = None

        try:
            # 尝试解析JSON
            data = json.loads(json_str)

            # 如果data字段是嵌套的JSON字符串，需要解析它
            if 'data' in data and isinstance(data['data'], str):
                try:
                    inner_data = json.loads(data['data'])
                    data['_parsed_data'] = inner_data
                except json.JSONDecodeError:
                    pass

            # 提取源单号（FMoBillNo）
            source_bill_no = self._extract_source_bill_no(data)

        except json.JSONDecodeError as e:
            # JSON解析失败，尝试用正则从截断的JSON中提取关键字段
            logger.debug(f"JSON不完整，尝试正则提取: {e}")
            data, source_bill_no = self._extract_from_truncated_json(json_str)

            if not data:
                # 正则提取也失败，尝试使用触发器数据
                if self._current_trigger:
                    logger.info(f"使用触发器数据填充请求: WONO={self._current_trigger.wono}")
                    data = {
                        '_from_trigger': True,
                        '_raw_request': json_str,
                        '_parsed_data': {
                            'FMoBillNo': self._current_trigger.wono,
                            'FFinishQty': float(self._current_trigger.cnt) if self._current_trigger.cnt else 0,
                            'FQuaQty': float(self._current_trigger.cnt) if self._current_trigger.cnt else 0,
                            'FMaterialId': {'FNumber': self._current_trigger.part_no},
                            'FLot': {'FNumber': self._current_trigger.pack_id},
                        }
                    }
                    source_bill_no = self._current_trigger.wono
                else:
                    logger.warning(f"无法从截断JSON提取数据且无触发器数据")
                    return

        except Exception as e:
            logger.warning(f"处理请求失败: {e}")
            return

        # 从触发器数据获取产线和源单号（如果缺失）
        line_name = ''
        if self._current_trigger:
            line_name = self._current_trigger.line
            # 如果source_bill_no为空，使用触发器数据的WONO
            if not source_bill_no:
                source_bill_no = self._current_trigger.wono
                logger.info(f"使用触发器数据填充源单号: {source_bill_no}")
            logger.debug(f"使用触发器中的产线: {line_name}")
        else:
            logger.warning(f"请求 {source_bill_no} 没有对应的触发器数据，产线将为空")

        # 设为当前请求（覆盖之前未完成的请求）
        if self._current_request:
            old_bill_no = self._current_request[2]
            logger.debug(f"覆盖未完成的请求: {old_bill_no}")

        self._current_request = (timestamp, data, source_bill_no, line_name)
        logger.debug(f"记录当前请求: {source_bill_no}, 产线: {line_name}")

    def _extract_from_truncated_json(self, json_str: str) -> Tuple[Optional[dict], Optional[str]]:
        """
        从截断的JSON字符串中提取关键字段

        EAI日志会截断过长的JSON，导致无法正常解析
        此方法使用正则从截断的字符串中提取需要的字段

        Args:
            json_str: 截断的JSON字符串

        Returns:
            (提取的数据字典, 源单号)
        """
        extracted = {
            '_truncated': True,
            '_raw_request': json_str
        }
        source_bill_no = None

        # 提取源单号（FMoBillNo优先，其次FSrcBillNo）
        for key in ['FMoBillNo', 'FSrcBillNo']:
            if key in self.FIELD_PATTERNS:
                match = self.FIELD_PATTERNS[key].search(json_str)
                if match:
                    source_bill_no = match.group(1)
                    extracted[key] = source_bill_no
                    break

        # 如果没找到源单号，这条请求可能不是报工相关的
        if not source_bill_no:
            return None, None

        # 提取其他字段
        for field_name, pattern in self.FIELD_PATTERNS.items():
            if field_name not in extracted:
                match = pattern.search(json_str)
                if match:
                    value = match.group(1)
                    # 处理数量字段为数值
                    if field_name in ['FFinishQty', 'FQuaQty']:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    extracted[field_name] = value

        # 构建兼容的数据结构
        extracted['_parsed_data'] = {
            'FMoBillNo': source_bill_no,
            'FFinishQty': extracted.get('FFinishQty', 0),
            'FQuaQty': extracted.get('FQuaQty', 0),
            'FMaterialId': {'FNumber': extracted.get('FMaterialId_FNumber', '')},
            'FLot': {'FNumber': extracted.get('FLot_FNumber', '')},  # 批次号
        }

        logger.info(f"从截断JSON提取到请求: {source_bill_no}")
        return extracted, source_bill_no

    def _handle_response(self, timestamp: datetime, json_str: str) -> Optional[ReportRecord]:
        """
        处理kingdee响应

        与当前请求精确配对：
        - 处理成功和失败响应
        - 配对后清空当前请求和触发器数据
        - 当请求被截断导致解析失败时，使用触发器数据直接配对

        Args:
            timestamp: 日志时间
            json_str: 响应JSON字符串

        Returns:
            成功或失败配对都返回ReportRecord，无法配对返回None
        """
        try:
            # 检查是否有待配对的请求
            use_trigger_fallback = False
            if not self._current_request:
                # 没有请求，但有触发器数据时，使用触发器数据直接配对
                if self._current_trigger:
                    logger.info(f"请求被截断，使用触发器数据直接配对: WONO={self._current_trigger.wono}, LINE={self._current_trigger.line}")
                    use_trigger_fallback = True
                    # 从触发器构造基本请求数据
                    req_data = {
                        '_from_trigger': True,
                        'WONO': self._current_trigger.wono,
                        'LINE': self._current_trigger.line,
                        'PACKID': self._current_trigger.pack_id,
                        'CNT': self._current_trigger.cnt,
                        'PARTNO': self._current_trigger.part_no,
                        '_parsed_data': {
                            'FMoBillNo': self._current_trigger.wono,
                            'FFinishQty': float(self._current_trigger.cnt) if self._current_trigger.cnt else 0,
                            'FQuaQty': float(self._current_trigger.cnt) if self._current_trigger.cnt else 0,
                            'FMaterialId': {'FNumber': self._current_trigger.part_no},
                            'FLot': {'FNumber': self._current_trigger.pack_id},
                        }
                    }
                    source_bill_no = self._current_trigger.wono
                    line_name = self._current_trigger.line
                else:
                    logger.warning("收到响应但没有待配对的请求且无触发器数据，跳过")
                    return None
            else:
                # 取出当前请求进行配对
                req_timestamp, req_data, source_bill_no, line_name = self._current_request
                if not line_name and self._current_trigger:
                    line_name = self._current_trigger.line
                    logger.info(f"补充 LINE（请求时触发器未就绪）: {line_name}")

            self._current_request = None  # 清空，确保不会重复配对
            self._current_trigger = None  # 清空触发器数据，本次流程完成

            # 判断是成功还是失败
            is_success = self.SUCCESS_PATTERN.search(json_str) is not None
            is_failure = self.FAILURE_PATTERN.search(json_str) is not None

            if is_success:
                # 成功响应处理
                try:
                    resp_data = json.loads(json_str)
                    schb_number = self._extract_schb_number_from_response(resp_data)
                    if not schb_number:
                        logger.warning("响应中未找到汇报单号")
                        return None

                    record = self._build_record(req_data, resp_data, json_str, schb_number, source_bill_no, line_name)
                    if record:
                        logger.info(f"解析到报工成功记录: 汇报单号={record.schb_number}, 源单号={record.source_bill_no}, 产线={record.line}")
                        return record
                except json.JSONDecodeError as e:
                    logger.warning(f"成功响应JSON解析失败: {e}")
                    return None

            elif is_failure:
                # 失败响应处理 - 提取错误信息
                error_message = self._extract_error_message(json_str)
                logger.info(f"解析到报工失败记录: 源单号={source_bill_no}, 错误={error_message[:100] if error_message else '未知错误'}")

                # 构建失败记录
                record = self._build_failure_record(
                    req_data=req_data,
                    raw_response=json_str,
                    source_bill_no=source_bill_no,
                    line_name=line_name,
                    error_message=error_message
                )
                return record

            else:
                logger.debug(f"响应状态不明确，跳过: {json_str[:100]}")
                return None

        except Exception as e:
            logger.warning(f"处理响应失败: {e}")
            return None

    def _extract_source_bill_no(self, data: dict) -> Optional[str]:
        """
        从请求数据中提取源单号（FMoBillNo）

        源单号是ACC系统发送的原始工单号，用于追溯

        Args:
            data: 请求JSON数据

        Returns:
            源单号
        """
        # 源单号字段优先级
        possible_keys = ['FMoBillNo', 'FSrcBillNo', 'FBillNo', 'SCHB_NUMBER', 'schb_number', 'BillNo']

        # 如果有解析后的嵌套数据，优先从那里查找
        search_data = data.get('_parsed_data', data)

        # 直接在根层级查找
        for key in possible_keys:
            if key in search_data:
                value = search_data[key]
                if value:
                    return str(value)

        # 在Model中查找
        if 'Model' in search_data:
            model = search_data['Model']
            for key in possible_keys:
                if key in model:
                    value = model[key]
                    if value:
                        return str(value)

        # 在FEntity数组中查找
        if 'FEntity' in search_data and isinstance(search_data['FEntity'], list) and search_data['FEntity']:
            entity = search_data['FEntity'][0]
            for key in possible_keys:
                if key in entity:
                    value = entity[key]
                    if value:
                        return str(value)

        # 递归搜索
        return self._recursive_search(search_data, possible_keys)

    def _recursive_search(self, data: dict, keys: List[str], depth: int = 3) -> Optional[str]:
        """递归搜索字典中的key"""
        if depth <= 0:
            return None

        if isinstance(data, dict):
            for key in keys:
                if key in data:
                    return str(data[key])
            for v in data.values():
                result = self._recursive_search(v, keys, depth - 1)
                if result:
                    return result

        elif isinstance(data, list):
            for item in data:
                result = self._recursive_search(item, keys, depth - 1)
                if result:
                    return result

        return None

    def _extract_schb_number_from_response(self, data: dict) -> Optional[str]:
        """
        从响应数据中提取工单号

        Args:
            data: 响应JSON数据

        Returns:
            工单号
        """
        # 响应中可能有不同的结构
        possible_keys = ['FBillNo', 'Number', 'BillNo', 'SCHB_NUMBER']

        # 在Result中查找
        if 'Result' in data and isinstance(data['Result'], dict):
            result = data['Result']
            if 'ResponseStatus' in result and isinstance(result['ResponseStatus'], dict):
                resp_status = result['ResponseStatus']
                for key in possible_keys:
                    if key in resp_status:
                        return str(resp_status[key])

            # 直接在Result中找
            for key in possible_keys:
                if key in result:
                    return str(result[key])

        return self._recursive_search(data, possible_keys)

    def _build_record(self, req_data: dict, resp_data: dict, raw_response: str,
                       schb_number: str, source_bill_no: str, line_name: str = '') -> Optional[ReportRecord]:
        """
        构建报工记录

        Args:
            req_data: 请求数据
            resp_data: 响应数据
            raw_response: 原始响应字符串
            schb_number: 系统生成的汇报单号（从响应中获取）
            source_bill_no: 源单号（从请求中获取，即WONO工单号）
            line_name: 产线名称（从触发器数据的LINE字段获取）

        Returns:
            ReportRecord对象
        """
        try:
            if not schb_number:
                return None

            # 提取其他字段
            # FFinishQty是报工数量, FQuaQty是合格数量
            qty = self._extract_field(req_data, ['FFinishQty', 'FQuaQty', 'FQty', 'Qty', 'qty', 'FMustQty'], default=0)
            product_code = self._extract_field(req_data, ['FMaterialId', 'FMaterialNumber', 'ProductCode', 'product_code'], default='')
            process_code = self._extract_field(req_data, ['FOperNumber', 'ProcessCode', 'process_code'], default='')
            worker_code = self._extract_field(req_data, ['FWorkerId', 'WorkerCode', 'worker_code', 'FWorkerNumber'], default='')
            lot_number = self._extract_field(req_data, ['FLot'], default='')  # 批次号

            # 如果请求数据来自触发器，直接使用触发器中的字段值作为备份
            if req_data.get('_from_trigger'):
                if not qty:
                    qty = float(req_data.get('CNT', 0) or 0)
                if not product_code:
                    product_code = req_data.get('PARTNO', '')
                if not lot_number:
                    lot_number = req_data.get('PACKID', '')

            # 处理数量
            if isinstance(qty, str):
                try:
                    qty = float(qty)
                except ValueError:
                    qty = 0

            # 处理原始请求内容（可能是截断的）
            if req_data.get('_truncated'):
                raw_request = req_data.get('_raw_request', '')
            else:
                raw_request = json.dumps(req_data, ensure_ascii=False)

            # 产线直接使用触发器数据中的LINE字段，不再推断
            logger.debug(f"产线来自触发器: LINE={line_name}, WONO={source_bill_no}")

            return ReportRecord(
                schb_number=schb_number,
                source_bill_no=source_bill_no or '',
                qty=float(qty) if qty else 0,
                product_code=str(product_code) if product_code else '',
                process_code=str(process_code) if process_code else '',
                report_time=datetime.now(),
                worker_code=str(worker_code) if worker_code else '',
                lot_number=str(lot_number) if lot_number else '',
                line=line_name or '',
                raw_request=raw_request,
                raw_response=raw_response,
                is_success=True
            )

        except Exception as e:
            logger.warning(f"构建记录失败: {e}")
            return None

    def _extract_field(self, data: dict, keys: List[str], default=None):
        """从数据中提取字段值"""
        # 优先从解析后的嵌套数据中查找
        search_data = data.get('_parsed_data', data)

        # 直接查找
        for key in keys:
            if key in search_data:
                value = search_data[key]
                # 处理嵌套对象，如 FMaterialId: {FNumber: xxx}
                if isinstance(value, dict) and 'FNumber' in value:
                    return value['FNumber']
                return value

        # 在Model中查找
        if 'Model' in search_data and isinstance(search_data['Model'], dict):
            model = search_data['Model']
            for key in keys:
                if key in model:
                    value = model[key]
                    if isinstance(value, dict) and 'FNumber' in value:
                        return value['FNumber']
                    return value

        # 在FEntity中查找
        if 'FEntity' in search_data and isinstance(search_data['FEntity'], list) and search_data['FEntity']:
            entity = search_data['FEntity'][0]
            for key in keys:
                if key in entity:
                    value = entity[key]
                    if isinstance(value, dict) and 'FNumber' in value:
                        return value['FNumber']
                    return value

        return default

    def _extract_error_message(self, json_str: str) -> str:
        """
        从响应JSON中提取错误信息

        优先从Errors数组中的Message字段提取，如果找不到则返回默认错误信息

        Args:
            json_str: 响应JSON字符串

        Returns:
            错误信息字符串
        """
        try:
            # 尝试解析JSON并从结构中提取
            data = json.loads(json_str)
            if 'Result' in data and isinstance(data['Result'], dict):
                result = data['Result']
                if 'ResponseStatus' in result and isinstance(result['ResponseStatus'], dict):
                    resp_status = result['ResponseStatus']
                    if 'Errors' in resp_status and isinstance(resp_status['Errors'], list):
                        errors = resp_status['Errors']
                        if errors:
                            # 合并所有错误信息
                            messages = []
                            for err in errors:
                                if isinstance(err, dict) and 'Message' in err:
                                    msg = err['Message']
                                    # 清理错误信息中的转义字符
                                    msg = msg.replace('\\r\\n', ' ').replace('\\n', ' ').replace('\\r', ' ')
                                    msg = msg.strip()
                                    if msg:
                                        messages.append(msg)
                            if messages:
                                return '; '.join(messages)
        except json.JSONDecodeError:
            pass

        # JSON解析失败，尝试用正则提取
        matches = self.ERROR_MESSAGE_PATTERN.findall(json_str)
        if matches:
            # 清理并返回第一个匹配的错误信息
            msg = matches[0].replace('\\r\\n', ' ').replace('\\n', ' ').replace('\\r', ' ')
            return msg.strip()

        return '执行错误'

    def _handle_lua_error(self, timestamp: datetime, json_str: str, raw_line: str) -> Optional[ReportRecord]:
        """
        处理Lua执行错误

        从嵌套JSON的errorMsg字段中提取详细错误信息

        Args:
            timestamp: 日志时间
            json_str: JSON字符串部分
            raw_line: 原始日志行

        Returns:
            失败记录
        """
        try:
            # 尝试解析外层JSON
            error_message = ''
            source_bill_no = ''
            line_name = ''

            try:
                # 尝试解析JSON
                data = json.loads(json_str)

                # 提取errorMsg
                if 'errorMsg' in data:
                    error_msg = data['errorMsg']
                    # errorMsg可能包含嵌套的JSON错误响应
                    if 'ERP报工返回失败' in error_msg:
                        # 尝试从errorMsg中提取嵌套的错误信息
                        nested_json_match = re.search(r'\{.*"Errors".*\}', error_msg)
                        if nested_json_match:
                            nested_error = self._extract_error_message(nested_json_match.group(0))
                            if nested_error and nested_error != '执行错误':
                                error_message = nested_error
                            else:
                                # 提取"ERP报工返回失败"后面的内容
                                error_message = error_msg.split('ERP报工返回失败')[1] if 'ERP报工返回失败' in error_msg else error_msg
                        else:
                            error_message = error_msg
                    else:
                        error_message = error_msg

                # 提取data字段中的信息
                if 'data' in data:
                    try:
                        inner_data = json.loads(data['data']) if isinstance(data['data'], str) else data['data']
                        line_name = inner_data.get('LINE', '')
                        # 尝试提取工单号
                        source_bill_no = inner_data.get('WONO', '')
                    except:
                        pass

            except json.JSONDecodeError:
                # JSON解析失败，尝试用正则提取
                # 提取errorMsg内容
                error_msg_match = re.search(r'"errorMsg"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', json_str)
                if error_msg_match:
                    error_message = error_msg_match.group(1)
                    # 解码转义字符
                    error_message = error_message.replace('\\n', ' ').replace('\\r', ' ')

                # 提取LINE
                line_match = re.search(r'"LINE"\s*:\s*"([^"]+)"', json_str)
                if line_match:
                    line_name = line_match.group(1)

                # 提取WONO
                wono_match = re.search(r'"WONO"\s*:\s*"([^"]+)"', json_str)
                if wono_match:
                    source_bill_no = wono_match.group(1)

            # 如果还没有获取到产线，尝试从触发器数据获取
            if not line_name and self._current_trigger:
                line_name = self._current_trigger.line
                if not source_bill_no:
                    source_bill_no = self._current_trigger.wono

            # 清理错误信息
            if error_message:
                # 清理多余的转义和格式
                error_message = error_message.replace('\\r\\n', ' ').replace('\\n', ' ').replace('\\r', ' ')
                error_message = re.sub(r'\s+', ' ', error_message).strip()
                # 截取有意义的部分
                if len(error_message) > 500:
                    error_message = error_message[:500] + '...'
            else:
                error_message = 'Lua执行错误'

            # 清空当前状态
            self._current_request = None
            self._current_trigger = None

            logger.info(f"解析到Lua错误记录: 源单号={source_bill_no}, 产线={line_name}, 错误={error_message[:100]}")

            # 生成唯一的失败记录ID
            fail_id = f"FAIL_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

            return ReportRecord(
                schb_number=fail_id,
                source_bill_no=source_bill_no or 'UNKNOWN',
                qty=0,
                product_code='',
                process_code='',
                report_time=timestamp,
                worker_code='',
                lot_number='',
                line=line_name,
                raw_request='',
                raw_response=raw_line[:2000],  # 保存原始日志行，限制长度
                is_success=False,
                error_message=error_message
            )

        except Exception as e:
            logger.warning(f"处理Lua错误失败: {e}")
            return None

    def _build_failure_record(self, req_data: dict, raw_response: str,
                               source_bill_no: str, line_name: str,
                               error_message: str) -> ReportRecord:
        """
        构建失败记录

        Args:
            req_data: 请求数据
            raw_response: 原始响应字符串
            source_bill_no: 源单号
            line_name: 产线名称
            error_message: 错误信息

        Returns:
            ReportRecord对象
        """
        # 处理原始请求内容
        if req_data.get('_truncated'):
            raw_request = req_data.get('_raw_request', '')
        else:
            raw_request = json.dumps(req_data, ensure_ascii=False)

        # 提取数量和产品编码（用于记录）
        qty = self._extract_field(req_data, ['FFinishQty', 'FQuaQty', 'FQty', 'Qty'], default=0)
        product_code = self._extract_field(req_data, ['FMaterialId', 'FMaterialNumber', 'ProductCode'], default='')
        lot_number = self._extract_field(req_data, ['FLot'], default='')

        # 如果请求数据来自触发器，使用触发器中的字段值作为备份
        if req_data.get('_from_trigger'):
            if not qty:
                qty = float(req_data.get('CNT', 0) or 0)
            if not product_code:
                product_code = req_data.get('PARTNO', '')
            if not lot_number:
                lot_number = req_data.get('PACKID', '')

        if isinstance(qty, str):
            try:
                qty = float(qty)
            except ValueError:
                qty = 0

        # 生成唯一的失败记录ID
        fail_id = f"FAIL_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        return ReportRecord(
            schb_number=fail_id,
            source_bill_no=source_bill_no or 'UNKNOWN',
            qty=float(qty) if qty else 0,
            product_code=str(product_code) if product_code else '',
            process_code='',
            report_time=datetime.now(),
            worker_code='',
            lot_number=str(lot_number) if lot_number else '',
            line=line_name or '',
            raw_request=raw_request,
            raw_response=raw_response[:4000],  # 限制长度
            is_success=False,
            error_message=error_message
        )
