# -*- coding: utf-8 -*-
"""
EAI日志监听服务 - 配置文件
用于本地测试和生产环境部署的配置分离
"""

import os

# =============================================================================
# 环境配置
# =============================================================================
# 'local' - 本地测试环境
# 'production' - 生产环境(165服务器)
ENV = os.getenv('EAI_MONITOR_ENV', 'local')

# =============================================================================
# EAI服务器配置
# =============================================================================
EAI_SERVER = {
    'host': '172.17.10.163',
    'port': 2200,
    'user': 'root',
    'password': 'Hangqu123',
    'log_dir': '/var/eai/logs/'
}

# =============================================================================
# ACC数据库配置
# =============================================================================
ACC_DATABASE = {
    'host': '172.17.10.165',
    'port': 1521,
    'service': 'orcl.ecdag.com',
    'schemas': {
        'dpepp1': {'user': 'iplant_dpepp1', 'password': 'acc'},
        'smt2': {'user': 'iplant_smt2', 'password': 'acc'},
        'dpeps1': {'user': 'iplant_dpeps1', 'password': 'acc'}
    }
}

# =============================================================================
# 日志文件与数据库映射
# =============================================================================
LOG_FILE_MAPPING = {
    # 注意：Linux上路径用反斜杠需要转义，实际文件名包含反斜杠
    r'FLOW_DP-EPS\IPA MES报工接口.log': {
        'schema': 'dpeps1',
        'description': 'DP-EPS IPA 产线'
    },
    r'FLOW_SMT\MID-Line2MES报工接口.log': {
        'schema': 'smt2',
        'description': 'SMT Line2 产线'
    },
    r'FLOW_DP-SMT\MID\EPP MES报工接口.log': {
        'schema': 'dpepp1',
        'description': 'DP-SMT MID EPP 产线'
    }
}

# =============================================================================
# 服务配置
# =============================================================================
SERVICE_CONFIG = {
    # 日志保留天数
    'log_retention_days': 30,

    # 重连间隔(秒)
    'reconnect_interval': 10,

    # 心跳间隔(秒)
    'heartbeat_interval': 60,

    # 批量插入阈值
    'batch_insert_size': 10,

    # 批量插入超时(秒)
    'batch_insert_timeout': 5,

    # 日志级别
    'log_level': 'INFO'
}

# =============================================================================
# 本地测试配置覆盖
# =============================================================================
if ENV == 'local':
    # 本地可能需要的特殊配置
    SERVICE_CONFIG['log_level'] = 'DEBUG'

# =============================================================================
# 生产环境配置覆盖
# =============================================================================
if ENV == 'production':
    SERVICE_CONFIG['log_level'] = 'INFO'


def get_dsn(schema_name):
    """
    获取Oracle数据库DSN字符串

    Args:
        schema_name: 模式名称 (dpepp1, smt2, dpeps1)

    Returns:
        DSN字符串
    """
    db = ACC_DATABASE
    return f"{db['host']}:{db['port']}/{db['service']}"


def get_connection_string(schema_name):
    """
    获取完整的数据库连接字符串

    Args:
        schema_name: 模式名称 (dpepp1, smt2, dpeps1)

    Returns:
        连接字符串 (user/password@host:port/service)
    """
    db = ACC_DATABASE
    schema = db['schemas'].get(schema_name)
    if not schema:
        raise ValueError(f"Unknown schema: {schema_name}")
    return f"{schema['user']}/{schema['password']}@{get_dsn(schema_name)}"


def get_log_file_path(log_file):
    """
    获取完整的日志文件路径

    Args:
        log_file: 相对日志文件路径

    Returns:
        完整路径
    """
    return f"{EAI_SERVER['log_dir']}{log_file}"
