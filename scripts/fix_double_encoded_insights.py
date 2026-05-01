#!/usr/bin/env python3
"""修复 global_insights 双重编码问题"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rss2cubox.db import fix_duplicate_encoded_insights

# 支持本地 DB 或 Neon DB
db_url = os.environ.get('LOCAL_DB_URL') or os.environ.get('NEON_DATABASE_URL')
if not db_url:
    print("请设置 LOCAL_DB_URL 或 NEON_DATABASE_URL 环境变量")
    sys.exit(1)

print(f"开始修复双重编码数据 (DB: {db_url[:30]}...)")
fixed = fix_duplicate_encoded_insights(db_url)
print(f"修复完成，共修复 {fixed} 条记录")